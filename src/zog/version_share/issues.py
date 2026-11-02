"""Native GitHub issue dependency inspection and explicitly authorized mutation."""
from urllib.parse import quote

from .core import ShareError, component, repository_path

MAXIMUM_ISSUES = 1000
MAXIMUM_DEPENDENCY_GRAPH = 1000


def repository_name(value):
    if not isinstance(value, str):
        raise ShareError('configuration', 'Repository must be OWNER/PROGRAM.')
    parts = value.split('/')
    if len(parts) != 2:
        raise ShareError('configuration', 'Repository must be OWNER/PROGRAM.')
    return component(parts[0]) + '/' + component(parts[1])


def issue_number(value):
    if type(value) is not int or value <= 0:
        raise ShareError('configuration', 'Issue number must be a positive integer.')
    return value


def _path(repository):
    owner, program = repository_name(repository).split('/')
    return repository_path(owner, program)


def _repository_from_issue(value):
    url = value.get('repository_url')
    prefix = 'https://api.github.com/repos/'
    if not isinstance(url, str) or not url.startswith(prefix):
        raise ShareError('remote', 'Issue response is missing a canonical repository URL.')
    return repository_name(url[len(prefix):])


def _summary(value):
    if not isinstance(value, dict) or type(value.get('id')) is not int or type(value.get('number')) is not int:
        raise ShareError('remote', 'Invalid issue response.')
    if value.get('pull_request') is not None:
        raise ShareError('unsupported', 'Pull requests are not supported as issue dependencies.')
    repository = _repository_from_issue(value)
    state = value.get('state')
    if state not in ('open', 'closed'):
        raise ShareError('remote', 'Invalid issue state.')
    return {
        'repository': repository,
        'number': value['number'],
        'id': value['id'],
        'state': state,
        'state_reason': value.get('state_reason'),
        'title': value.get('title', ''),
        'url': value.get('html_url') or 'https://github.com/' + repository + '/issues/' + str(value['number']),
        'updated_at': value.get('updated_at'),
    }


def list_issues(client, repository, state='open', limit=100):
    repository = repository_name(repository)
    if state not in ('open', 'closed', 'all'):
        raise ShareError('configuration', 'Issue state must be open, closed or all.')
    if type(limit) is not int or limit <= 0 or limit > MAXIMUM_ISSUES:
        raise ShareError('configuration', 'Issue list limit must be between 1 and %d.' % MAXIMUM_ISSUES)
    result, page = [], 1
    while len(result) < limit:
        remaining = min(100, limit - len(result))
        batch = client.request(
            'GET',
            _path(repository) + '/issues?state=' + quote(state, safe='') +
            '&per_page=' + str(remaining) + '&page=' + str(page))
        if not isinstance(batch, list):
            raise ShareError('remote', 'Invalid issue list response.')
        for value in batch:
            if value.get('pull_request') is not None:
                continue
            result.append(_summary(value))
            if len(result) == limit:
                break
        if len(batch) < remaining:
            break
        page += 1
    return result


def show_issue(client, repository, number):
    repository = repository_name(repository)
    number = issue_number(number)
    value = client.request('GET', _path(repository) + '/issues/' + str(number))
    result = _summary(value)
    if result['repository'].lower() != repository.lower() or result['number'] != number:
        raise ShareError('integrity', 'GitHub returned a different issue than requested.')
    return result


def _dependency_list(client, repository, number, direction):
    repository = repository_name(repository)
    number = issue_number(number)
    if direction not in ('blocked_by', 'blocking'):
        raise ShareError('configuration', 'Invalid dependency direction.')
    result, page = [], 1
    while True:
        batch = client.request(
            'GET',
            _path(repository) + '/issues/' + str(number) +
            '/dependencies/' + direction + '?per_page=100&page=' + str(page))
        if not isinstance(batch, list):
            raise ShareError('remote', 'Invalid issue dependency response.')
        result.extend(_summary(value) for value in batch)
        if len(result) > MAXIMUM_ISSUES:
            raise ShareError('unsupported', 'Issue dependency list exceeds %d entries.' % MAXIMUM_ISSUES)
        if len(batch) < 100:
            return result
        page += 1


def inspect_dependencies(client, repository, number):
    issue = show_issue(client, repository, number)
    return {
        'issue': issue,
        'blocked_by': _dependency_list(client, issue['repository'], issue['number'], 'blocked_by'),
        'blocking': _dependency_list(client, issue['repository'], issue['number'], 'blocking'),
    }


def _require_authorized(authorized):
    if authorized is not True:
        raise ShareError(
            'configuration',
            'Issue dependency mutation requires explicit authorization (authorized=True / --authorize).')


def _require_open(issue, role):
    if issue['state'] != 'open':
        raise ShareError('conflict', '%s issue is closed; dependency mutation requires open issues.' % role)


def _has_dependency(client, issue, blocker_id):
    return any(
        dependency['id'] == blocker_id
        for dependency in _dependency_list(
            client, issue['repository'], issue['number'], 'blocked_by'))


def _would_cycle(client, blocker, subject_id):
    pending = [blocker]
    seen = set()
    while pending:
        current = pending.pop()
        if current['id'] == subject_id:
            return True
        if current['id'] in seen:
            continue
        seen.add(current['id'])
        if len(seen) > MAXIMUM_DEPENDENCY_GRAPH:
            raise ShareError(
                'unsupported',
                'Dependency graph exceeds %d issues; refusing an unverified mutation.' %
                MAXIMUM_DEPENDENCY_GRAPH)
        pending.extend(
            _dependency_list(
                client, current['repository'], current['number'], 'blocked_by'))
    return False


def _post_read(client, subject, blocker, expect_linked, mutation_error):
    try:
        after_subject = show_issue(client, subject['repository'], subject['number'])
        after_blocker = show_issue(client, blocker['repository'], blocker['number'])
        if after_subject['id'] != subject['id'] or after_blocker['id'] != blocker['id']:
            raise ShareError('integrity', 'Issue identity changed during dependency reconciliation.')
        linked = _has_dependency(client, after_subject, blocker['id'])
    except ShareError as error:
        if mutation_error is None:
            raise ShareError(
                'uncertain',
                'Dependency mutation completed but read-after verification failed; inspect GitHub before retrying.',
                'uncertain') from None
        if mutation_error.outcome == 'uncertain':
            raise ShareError(
                'uncertain',
                'Dependency mutation response and read-after verification are ambiguous; inspect GitHub before retrying.',
                'uncertain') from None
        raise error

    if linked != expect_linked:
        if mutation_error is not None and mutation_error.outcome != 'uncertain':
            raise mutation_error
        raise ShareError(
            'uncertain',
            'Read-after verification did not confirm the requested dependency state; inspect GitHub before retrying.',
            'uncertain')

    if after_subject['state'] != 'open' or after_blocker['state'] != 'open':
        raise ShareError(
            'conflict',
            'Issue state changed during dependency mutation; the dependency state was reconciled but requires inspection.',
            'published')

    return after_subject, after_blocker, linked


def _result(action, subject, blocker, changed, linked, reconciled):
    return {
        'action': action,
        'issue': subject,
        'blocked_by': blocker,
        'changed': changed,
        'linked': linked,
        'reconciled': reconciled,
    }


def link_dependency(client, repository, number, blocking_repository, blocking_number, authorized=False):
    _require_authorized(authorized)
    subject = show_issue(client, repository, number)
    blocker = show_issue(client, blocking_repository, blocking_number)
    _require_open(subject, 'Blocked')
    _require_open(blocker, 'Blocking')
    if subject['id'] == blocker['id']:
        raise ShareError('conflict', 'An issue cannot be blocked by itself.')
    if _has_dependency(client, subject, blocker['id']):
        return _result('link', subject, blocker, False, True, False)
    if _would_cycle(client, blocker, subject['id']):
        raise ShareError('conflict', 'Dependency would create a cycle.')

    error = None
    try:
        client.request(
            'POST',
            _path(subject['repository']) + '/issues/' + str(subject['number']) +
            '/dependencies/blocked_by',
            {'issue_id': blocker['id']})
    except ShareError as caught:
        if caught.code not in ('conflict', 'network', 'remote') and caught.outcome != 'uncertain':
            raise
        error = caught

    after_subject, after_blocker, linked = _post_read(client, subject, blocker, True, error)
    return _result('link', after_subject, after_blocker, True, linked, error is not None)


def unlink_dependency(client, repository, number, blocking_repository, blocking_number, authorized=False):
    _require_authorized(authorized)
    subject = show_issue(client, repository, number)
    blocker = show_issue(client, blocking_repository, blocking_number)
    _require_open(subject, 'Blocked')
    _require_open(blocker, 'Blocking')
    if not _has_dependency(client, subject, blocker['id']):
        return _result('unlink', subject, blocker, False, False, False)

    error = None
    try:
        client.request(
            'DELETE',
            _path(subject['repository']) + '/issues/' + str(subject['number']) +
            '/dependencies/blocked_by/' + str(blocker['id']))
    except ShareError as caught:
        if caught.code not in ('conflict', 'network', 'remote') and caught.outcome != 'uncertain':
            raise
        error = caught

    after_subject, after_blocker, linked = _post_read(client, subject, blocker, False, error)
    return _result('unlink', after_subject, after_blocker, True, linked, error is not None)
