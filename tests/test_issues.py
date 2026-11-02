import io
import json
from urllib.parse import parse_qs, urlsplit
import unittest
from unittest.mock import patch

from zog.version_share import ShareError
from zog.version_share.__main__ import main
from zog.version_share.issues import (inspect_dependencies, link_dependency, list_issues,
                                      show_issue, unlink_dependency)


class IssueServer:
    _token = 'offline-issue-token'

    def __init__(self):
        self.calls = []
        self.permission_fail = False
        self.fail_before = None
        self.fail_after = None
        self.vanish_on_write = None
        self.issues = {}
        self.dependencies = {}
        self.add('owner/a', 1, 101, 'A one')
        self.add('owner/a', 2, 102, 'A two')
        self.add('owner/b', 7, 207, 'B seven')
        self.add('other/c', 3, 303, 'C three')
        self.add('owner/a', 99, 199, 'PR', pull_request=True)

    def add(self, repository, number, issue_id, title, state='open', pull_request=False):
        issue = {
            'id': issue_id,
            'number': number,
            'state': state,
            'state_reason': None,
            'title': title,
            'html_url': 'https://github.com/%s/issues/%d' % (repository, number),
            'repository_url': 'https://api.github.com/repos/' + repository,
            'updated_at': '2026-11-02T12:00:00Z',
        }
        if pull_request:
            issue['pull_request'] = {'url': 'https://api.github.com/pulls/1'}
        self.issues[(repository, number)] = issue
        self.dependencies.setdefault(issue_id, set())

    def by_id(self, issue_id):
        for issue in self.issues.values():
            if issue['id'] == issue_id:
                return issue
        return None

    def request(self, method, path, body=None):
        self.calls.append((method, path, body))
        key = method
        if self.fail_before == key:
            self.fail_before = None
            raise ShareError('network', 'simulated ambiguous request', 'uncertain')
        result = self.handle(method, path, body)
        if self.fail_after == key:
            self.fail_after = None
            raise ShareError('network', 'simulated lost response', 'uncertain')
        return result

    def handle(self, method, path, body):
        parsed = urlsplit(path)
        pieces = parsed.path.strip('/').split('/')
        if len(pieces) < 4 or pieces[0] != 'repos':
            raise AssertionError((method, path, body))
        repository = pieces[1] + '/' + pieces[2]
        if pieces[3] != 'issues':
            raise AssertionError((method, path, body))

        if len(pieces) == 4 and method == 'GET':
            query = parse_qs(parsed.query)
            state = query.get('state', ['open'])[0]
            page = int(query.get('page', ['1'])[0])
            per_page = int(query.get('per_page', ['30'])[0])
            values = [dict(issue) for (repo, _), issue in sorted(self.issues.items())
                      if repo == repository and (state == 'all' or issue['state'] == state)]
            start = (page - 1) * per_page
            return values[start:start + per_page]

        number = int(pieces[4])
        issue = self.issues.get((repository, number))
        if issue is None:
            raise ShareError('not-found', 'issue missing')

        if len(pieces) == 5 and method == 'GET':
            return dict(issue)

        if len(pieces) >= 7 and pieces[5] == 'dependencies':
            direction = pieces[6]
            if direction == 'blocked_by' and method == 'GET' and len(pieces) == 7:
                values = [dict(self.by_id(value)) for value in sorted(self.dependencies[issue['id']])]
                return [value for value in values if value is not None]
            if direction == 'blocking' and method == 'GET' and len(pieces) == 7:
                values = []
                for subject_id, blockers in self.dependencies.items():
                    if issue['id'] in blockers:
                        subject = self.by_id(subject_id)
                        if subject is not None:
                            values.append(dict(subject))
                return values
            if direction == 'blocked_by' and method == 'POST' and len(pieces) == 7:
                if self.permission_fail:
                    raise ShareError('forbidden', 'denied', 'not-published')
                blocking_id = body['issue_id']
                if self.vanish_on_write == blocking_id:
                    stale = self.by_id(blocking_id)
                    if stale is not None:
                        self.issues.pop((stale['repository_url'].split('/repos/', 1)[1], stale['number']))
                    raise ShareError('not-found', 'blocking issue disappeared', 'not-published')
                if self.by_id(blocking_id) is None:
                    raise ShareError('not-found', 'blocking issue missing', 'not-published')
                if blocking_id in self.dependencies[issue['id']]:
                    raise ShareError('conflict', 'duplicate', 'not-published')
                self.dependencies[issue['id']].add(blocking_id)
                return dict(issue)
            if direction == 'blocked_by' and method == 'DELETE' and len(pieces) == 8:
                if self.permission_fail:
                    raise ShareError('forbidden', 'denied', 'not-published')
                blocking_id = int(pieces[7])
                self.dependencies[issue['id']].discard(blocking_id)
                return dict(issue)

        raise AssertionError((method, path, body))


class IssueDependencyTests(unittest.TestCase):
    def setUp(self):
        self.client = IssueServer()

    def mutations(self, method=None):
        return [call for call in self.client.calls
                if call[0] != 'GET' and (method is None or call[0] == method)]

    def test_read_only_list_show_and_dependency_inspection(self):
        self.client.dependencies[101].add(207)
        self.client.dependencies[303].add(101)
        listed = list_issues(self.client, 'owner/a', state='all')
        self.assertEqual([item['number'] for item in listed], [1, 2])
        shown = show_issue(self.client, 'owner/a', 1)
        self.assertEqual(shown['id'], 101)
        inspected = inspect_dependencies(self.client, 'owner/a', 1)
        self.assertEqual([(x['repository'], x['number']) for x in inspected['blocked_by']],
                         [('owner/b', 7)])
        self.assertEqual([(x['repository'], x['number']) for x in inspected['blocking']],
                         [('other/c', 3)])
        self.assertEqual(self.mutations(), [])

    def test_cross_repository_link_and_unlink(self):
        linked = link_dependency(self.client, 'owner/a', 1, 'other/c', 3, authorized=True)
        self.assertTrue(linked['changed'])
        self.assertTrue(linked['linked'])
        self.assertFalse(linked['reconciled'])
        post = self.mutations('POST')
        self.assertEqual(len(post), 1)
        self.assertEqual(post[0][2], {'issue_id': 303})
        inspected = inspect_dependencies(self.client, 'owner/a', 1)
        self.assertEqual(inspected['blocked_by'][0]['repository'], 'other/c')

        unlinked = unlink_dependency(self.client, 'owner/a', 1, 'other/c', 3, authorized=True)
        self.assertTrue(unlinked['changed'])
        self.assertFalse(unlinked['linked'])
        self.assertEqual(len(self.mutations('DELETE')), 1)

    def test_mutation_requires_explicit_authorization(self):
        with self.assertRaises(ShareError) as caught:
            link_dependency(self.client, 'owner/a', 1, 'owner/b', 7)
        self.assertEqual(caught.exception.code, 'configuration')
        self.assertEqual(self.client.calls, [])

    def test_duplicate_link_and_absent_unlink_are_idempotent(self):
        self.client.dependencies[101].add(207)
        linked = link_dependency(self.client, 'owner/a', 1, 'owner/b', 7, authorized=True)
        self.assertFalse(linked['changed'])
        self.assertTrue(linked['linked'])
        self.assertEqual(self.mutations(), [])

        self.client.dependencies[101].clear()
        self.client.calls.clear()
        unlinked = unlink_dependency(self.client, 'owner/a', 1, 'owner/b', 7, authorized=True)
        self.assertFalse(unlinked['changed'])
        self.assertFalse(unlinked['linked'])
        self.assertEqual(self.mutations(), [])

    def test_closed_stale_issue_is_rejected_before_write(self):
        self.client.issues[('owner/b', 7)]['state'] = 'closed'
        with self.assertRaises(ShareError) as caught:
            link_dependency(self.client, 'owner/a', 1, 'owner/b', 7, authorized=True)
        self.assertEqual(caught.exception.code, 'conflict')
        self.assertEqual(self.mutations(), [])

    def test_issue_disappearing_between_read_and_write_is_not_published(self):
        self.client.vanish_on_write = 207
        with self.assertRaises(ShareError) as caught:
            link_dependency(self.client, 'owner/a', 1, 'owner/b', 7, authorized=True)
        self.assertEqual(caught.exception.code, 'not-found')
        self.assertEqual(caught.exception.outcome, 'not-published')
        self.assertEqual(len(self.mutations('POST')), 1)

    def test_indirect_cycle_is_rejected_before_write(self):
        self.client.dependencies[207].add(303)
        self.client.dependencies[303].add(101)
        with self.assertRaises(ShareError) as caught:
            link_dependency(self.client, 'owner/a', 1, 'owner/b', 7, authorized=True)
        self.assertEqual(caught.exception.code, 'conflict')
        self.assertIn('cycle', str(caught.exception).lower())
        self.assertEqual(self.mutations(), [])

    def test_permission_failure_is_definitive(self):
        self.client.permission_fail = True
        with self.assertRaises(ShareError) as caught:
            link_dependency(self.client, 'owner/a', 1, 'owner/b', 7, authorized=True)
        self.assertEqual(caught.exception.code, 'forbidden')
        self.assertEqual(caught.exception.outcome, 'not-published')

    def test_lost_link_response_reconciles_applied_state(self):
        self.client.fail_after = 'POST'
        result = link_dependency(self.client, 'owner/a', 1, 'owner/b', 7, authorized=True)
        self.assertTrue(result['linked'])
        self.assertTrue(result['changed'])
        self.assertTrue(result['reconciled'])
        self.assertIn(207, self.client.dependencies[101])

    def test_ambiguous_link_not_observed_remains_uncertain(self):
        self.client.fail_before = 'POST'
        with self.assertRaises(ShareError) as caught:
            link_dependency(self.client, 'owner/a', 1, 'owner/b', 7, authorized=True)
        self.assertEqual(caught.exception.code, 'uncertain')
        self.assertEqual(caught.exception.outcome, 'uncertain')
        self.assertNotIn(207, self.client.dependencies[101])

    def test_lost_unlink_response_reconciles_removed_state(self):
        self.client.dependencies[101].add(207)
        self.client.fail_after = 'DELETE'
        result = unlink_dependency(self.client, 'owner/a', 1, 'owner/b', 7, authorized=True)
        self.assertFalse(result['linked'])
        self.assertTrue(result['changed'])
        self.assertTrue(result['reconciled'])
        self.assertNotIn(207, self.client.dependencies[101])

    def test_cli_link_requires_authorize_and_accepts_bare_program_names(self):
        with patch('zog.version_share.__main__.GitHub.from_file', return_value=self.client):
            output = io.StringIO()
            with patch('sys.stdout', output):
                status = main(['--token-file', 'unused', '--owner', 'owner', '--json',
                               'issues', 'link', 'a', '1', 'b', '7'])
            self.assertEqual(status, 2)
            self.assertEqual(json.loads(output.getvalue())['error']['code'], 'configuration')

            output = io.StringIO()
            with patch('sys.stdout', output):
                status = main(['--token-file', 'unused', '--owner', 'owner', '--json',
                               'issues', 'link', 'a', '1', 'b', '7', '--authorize'])
            self.assertEqual(status, 0)
            result = json.loads(output.getvalue())['result']
            self.assertEqual(result['blocked_by']['repository'], 'owner/b')


if __name__ == '__main__':
    unittest.main()
