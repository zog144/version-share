"""Local snapshots, secret checks and durable publication records (Linux)."""
import base64
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
from .core import ShareError, safe_path

MAXIMUM_SOURCE = 64 * 1024 * 1024
MAXIMUM_CHANGED = 64 * 1024 * 1024
MAXIMUM_FILES = 10000
SCAN_CHUNK = 1024 * 1024
IGNORED_DIRECTORIES = {'.git', '.version-share', '__pycache__', '.pytest_cache', '.venv'}
SECRET_NAMES = {'github-token.txt', 'credentials', 'credentials.json', 'credentials.csv',
                'id_rsa', 'id_ed25519', '.netrc', '.pypirc'}
SECRET_PATTERN = re.compile(rb'(?:github_pat_[A-Za-z0-9_]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|'
                            rb'(?:AKIA|ASIA)[A-Z0-9]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----)')


def object_hash(kind, content):
    return hashlib.sha1(kind.encode() + b' ' + str(len(content)).encode() + b'\0' + content).hexdigest()


def ignored(path):
    parts = Path(path).parts
    name = parts[-1].lower()
    return (any(p in IGNORED_DIRECTORIES for p in parts) or name.endswith(('.pyc', '.pyo')) or
            name in SECRET_NAMES or name.endswith(('.pem', '.key')) or
            (name.startswith('.env') and name not in ('.env.example', '.env.sample')) or
            name.endswith(('_credentials.csv', '_accesskeys.csv')))


def guard_secret(content, token):
    if (token and token.encode() in content) or SECRET_PATTERN.search(content):
        raise ShareError('secret', 'Possible credential in outgoing content; publication stopped.', 'not-published')


def _scan_regular(entry, name, token):
    descriptor = os.open(entry, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, 'rb') as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise ShareError('unsafe-tree', 'Source entry changed type while scanning: ' + name)
        size = info.st_size
        digest = hashlib.sha1()
        digest.update(b'blob ' + str(size).encode() + b'\0')
        token_overlap = max(64, len(token.encode()) - 1 if token else 0)
        tail = b''
        seen = 0
        while True:
            chunk = source.read(SCAN_CHUNK)
            if not chunk:
                break
            seen += len(chunk)
            digest.update(chunk)
            guard_secret(tail + chunk, token)
            if token_overlap:
                tail = (tail + chunk)[-token_overlap:]
        if seen != size:
            raise ShareError('local', 'Source file changed size while scanning: ' + name)
        final = os.fstat(source.fileno())
        if (final.st_size != size or final.st_mtime_ns != info.st_mtime_ns or
                stat.S_IMODE(final.st_mode) != stat.S_IMODE(info.st_mode)):
            raise ShareError('local', 'Source file changed while scanning: ' + name)
        git_mode = '100755' if info.st_mode & 0o111 else '100644'
        return {'sha': digest.hexdigest(), 'mode': git_mode, 'size': size}


def scan_source(directory, token=''):
    """Stream and credential-scan the full source without retaining file contents."""
    root = Path(directory).resolve()
    files, excluded = {}, []
    source_bytes = 0

    def visit(folder):
        nonlocal source_bytes
        for entry in sorted(folder.iterdir()):
            name = entry.relative_to(root).as_posix()
            if ignored(name):
                excluded.append(name)
                continue
            safe_path(name)
            mode = entry.lstat().st_mode
            if stat.S_ISLNK(mode):
                target = os.readlink(entry)
                try:
                    resolved = entry.resolve(strict=True).relative_to(root)
                except (OSError, ValueError, RuntimeError):
                    raise ShareError('unsafe-tree', 'Symbolic link escapes source or forms a cycle.') from None
                if os.path.isabs(target) or '\\' in target or ignored(str(resolved)):
                    raise ShareError('unsafe-tree', 'Symbolic link points outside publishable source.')
                content = target.encode('utf-8')
                guard_secret(name.encode() + b'\0' + content, token)
                item = {'sha': object_hash('blob', content), 'mode': '120000', 'size': len(content)}
            elif stat.S_ISDIR(mode):
                visit(entry)
                continue
            elif stat.S_ISREG(mode):
                guard_secret(name.encode(), token)
                item = _scan_regular(entry, name, token)
            else:
                raise ShareError('unsupported', 'Only regular files and safe symbolic links can be published.')
            if len(files) >= MAXIMUM_FILES:
                raise ShareError(
                    'unsupported',
                    'Publication source exceeds the file-count limit of %d files.' % MAXIMUM_FILES)
            files[name] = item
            source_bytes += item['size']

    visit(root)
    return files, excluded, {'source_bytes_scanned': source_bytes, 'source_files': len(files)}


def delta_stats(before, scanned, delta, source_stats):
    content_names = sorted(
        name for name in delta['added'] + delta['modified']
        if before.get(name, {}).get('sha') != scanned[name]['sha'])
    changed_bytes = sum(scanned[name]['size'] for name in content_names)
    return {
        'source_bytes_scanned': source_stats['source_bytes_scanned'],
        'source_files': source_stats['source_files'],
        'changed_files': sum(len(delta[k]) for k in ('added', 'deleted', 'modified')),
        'content_files': len(content_names),
        'changed_bytes': changed_bytes,
    }


def _read_frozen(root, name, expected, token):
    entry = root / name
    mode = entry.lstat().st_mode
    if expected['mode'] == '120000':
        if not stat.S_ISLNK(mode):
            raise ShareError('local', 'Source changed after manifest scan: ' + name)
        target = os.readlink(entry)
        try:
            resolved = entry.resolve(strict=True).relative_to(root)
        except (OSError, ValueError, RuntimeError):
            raise ShareError('unsafe-tree', 'Symbolic link escapes source or forms a cycle.') from None
        if os.path.isabs(target) or '\\' in target or ignored(str(resolved)):
            raise ShareError('unsafe-tree', 'Symbolic link points outside publishable source.')
        content = target.encode('utf-8')
        git_mode = '120000'
    else:
        if not stat.S_ISREG(mode):
            raise ShareError('local', 'Source changed after manifest scan: ' + name)
        descriptor = os.open(entry, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(descriptor, 'rb') as source:
            info = os.fstat(source.fileno())
            git_mode = '100755' if info.st_mode & 0o111 else '100644'
            content = source.read(expected['size'] + 1)
            final = os.fstat(source.fileno())
        if len(content) != expected['size'] or final.st_size != expected['size'] or final.st_mtime_ns != info.st_mtime_ns:
            raise ShareError('local', 'Source changed after manifest scan: ' + name)
    guard_secret(name.encode() + b'\0' + content, token)
    if git_mode != expected['mode'] or object_hash('blob', content) != expected['sha']:
        raise ShareError('local', 'Source changed after manifest scan: ' + name)
    return content


def _verify_scanned(root, name, expected, token):
    entry = root / name
    mode = entry.lstat().st_mode
    if expected['mode'] == '120000':
        if not stat.S_ISLNK(mode):
            raise ShareError('local', 'Source changed after manifest scan: ' + name)
        target = os.readlink(entry)
        try:
            resolved = entry.resolve(strict=True).relative_to(root)
        except (OSError, ValueError, RuntimeError):
            raise ShareError('unsafe-tree', 'Symbolic link escapes source or forms a cycle.') from None
        if os.path.isabs(target) or '\\' in target or ignored(str(resolved)):
            raise ShareError('unsafe-tree', 'Symbolic link points outside publishable source.')
        content = target.encode('utf-8')
        guard_secret(name.encode() + b'\0' + content, token)
        actual = {'sha': object_hash('blob', content), 'mode': '120000', 'size': len(content)}
    else:
        if not stat.S_ISREG(mode):
            raise ShareError('local', 'Source changed after manifest scan: ' + name)
        actual = _scan_regular(entry, name, token)
    if actual != expected:
        raise ShareError('local', 'Source changed after manifest scan: ' + name)


def freeze_delta(directory, before, scanned, delta, token='', maximum_changed=MAXIMUM_CHANGED):
    """Freeze bytes only for content changes; mode-only edits reuse baseline blobs."""
    if type(maximum_changed) is not int or maximum_changed <= 0:
        raise ShareError('configuration', 'maximum_changed must be a positive byte count.')
    root = Path(directory).resolve()
    delta_files = {}
    content_names = []
    total = 0
    for name in sorted(delta['added'] + delta['modified']):
        item = scanned[name]
        prior = before.get(name)
        if prior and prior['sha'] == item['sha']:
            _verify_scanned(root, name, item, token)
            delta_files[name] = {'sha': item['sha'], 'mode': item['mode']}
            continue
        total += item['size']
        if total > maximum_changed:
            mib = maximum_changed / (1024 * 1024)
            label = str(int(mib)) if mib.is_integer() else ('%.2f' % mib).rstrip('0').rstrip('.')
            raise ShareError(
                'unsupported',
                'Changed publication content exceeds %d bytes (%s MiB); reached %d bytes at %s.'
                % (maximum_changed, label, total, name))
        content_names.append(name)
    for name in content_names:
        item = scanned[name]
        content = _read_frozen(root, name, item, token)
        delta_files[name] = {'sha': item['sha'], 'mode': item['mode'],
                             'content': base64.b64encode(content).decode()}
    return delta_files


def snapshot(directory, token='', maximum_source=MAXIMUM_SOURCE):
    if type(maximum_source) is not int or maximum_source <= 0:
        raise ShareError('configuration', 'maximum_source must be a positive byte count.')
    root = Path(directory).resolve()
    files, excluded, total = {}, [], 0
    def visit(folder):
        nonlocal total
        for entry in sorted(folder.iterdir()):
            name = entry.relative_to(root).as_posix()
            if ignored(name):
                excluded.append(name)
                continue
            safe_path(name)
            mode = entry.lstat().st_mode
            if stat.S_ISLNK(mode):
                target = os.readlink(entry)
                try:
                    resolved = entry.resolve(strict=True).relative_to(root)
                except (OSError, ValueError, RuntimeError):
                    raise ShareError('unsafe-tree', 'Symbolic link escapes source or forms a cycle.') from None
                if os.path.isabs(target) or '\\' in target or ignored(str(resolved)):
                    raise ShareError('unsafe-tree', 'Symbolic link points outside publishable source.')
                content, git_mode = target.encode('utf-8'), '120000'
            elif stat.S_ISDIR(mode):
                visit(entry)
                continue
            elif stat.S_ISREG(mode):
                # Do not follow a symlink substituted between lstat and open.
                descriptor = os.open(entry, os.O_RDONLY | os.O_NOFOLLOW)
                with os.fdopen(descriptor, 'rb') as source:
                    content = source.read(maximum_source + 1)
                git_mode = '100755' if mode & 0o111 else '100644'
            else:
                raise ShareError('unsupported', 'Only regular files and safe symbolic links can be published.')
            total += len(content)
            if total > maximum_source:
                mib = maximum_source / (1024 * 1024)
                label = str(int(mib)) if mib.is_integer() else ('%.2f' % mib).rstrip('0').rstrip('.')
                raise ShareError(
                    'unsupported',
                    'Publication source exceeds %d bytes (%s MiB); reached at least %d bytes while reading %s.'
                    % (maximum_source, label, total, name))
            if len(files) >= MAXIMUM_FILES:
                raise ShareError(
                    'unsupported',
                    'Publication source exceeds the file-count limit of %d files.' % MAXIMUM_FILES)
            guard_secret(name.encode() + b'\0' + content, token)
            files[name] = {'sha': object_hash('blob', content), 'mode': git_mode,
                           'content': base64.b64encode(content).decode()}
    visit(root)
    return files, excluded


def manifest(files):
    return {name: {'sha': item['sha'], 'mode': item['mode']} for name, item in files.items()}


def changes(before, after):
    return {'added': sorted(after.keys() - before.keys()),
            'deleted': sorted(before.keys() - after.keys()),
            'modified': sorted(name for name in before.keys() & after.keys() if before[name] != after[name])}


def read_json(path):
    try:
        return json.loads(Path(path).read_text())
    except (ValueError, OSError, UnicodeError):
        raise ShareError('local', 'Cannot read working-copy state; retrieve a fresh copy if state is damaged.') from None


def state_directory(directory):
    root = Path(directory).resolve()
    state = root / '.version-share'
    if state.is_symlink() or not state.is_dir():
        raise ShareError('configuration', 'Expected a retrieved working copy with .version-share state.')
    return state


@contextmanager
def locked(directory):
    state = state_directory(directory)
    descriptor = os.open(state / 'lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ShareError('conflict', 'Another publication is using this working copy.') from None
        yield state


def save_json(path, value):
    path = Path(path)
    descriptor, temporary = tempfile.mkstemp(prefix='.record-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w') as output:
            json.dump(value, output, sort_keys=True, indent=2)
            output.write('\n')
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
