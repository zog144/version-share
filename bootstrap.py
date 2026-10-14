#!/usr/bin/env python3
"""Retrieve a pinned version-share source tree using only Python's standard library."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import re
import types
import urllib.error
import urllib.request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--token-file', required=True)
    parser.add_argument('--commit', required=True)
    parser.add_argument('--destination', required=True)
    parser.add_argument('--owner', default='zog144')
    args = parser.parse_args()
    if not re.fullmatch('[0-9a-f]{40}', args.commit) or not re.fullmatch('[A-Za-z0-9-]+', args.owner):
        parser.error('Expected a full commit identifier and a GitHub owner name.')
    try:
        token = Path(args.token_file).read_text().strip()
        if not token or any(character.isspace() for character in token):
            raise ValueError('invalid token file')
        request = urllib.request.Request(
            'https://api.github.com/repos/' + args.owner + '/version-share/contents/src/zog/version_share/core.py?ref=' + args.commit,
            headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json',
                     'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': 'version-share-bootstrap/0.2.0'})
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=30) as response:
            raw = response.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise ValueError('oversized bootstrap response')
        body = json.loads(raw)
        if body['encoding'] != 'base64':
            raise ValueError('unexpected encoding')
        source = base64.b64decode(''.join(body['content'].split()), validate=True)
        actual = hashlib.sha1(b'blob ' + str(len(source)).encode() + b'\0' + source).hexdigest()
        if actual != body['sha']:
            raise ValueError('bootstrap integrity failure')
        module = types.ModuleType('zog_version_share_core')
        exec(compile(source, 'pinned-version-share-core.py', 'exec'), module.__dict__)
        result = module.retrieve(module.GitHub(token), args.owner, 'version-share', args.destination, args.commit)
        print(json.dumps(result).replace(token, '[REDACTED]'))
        return 0
    except Exception:
        # Avoid printing network bodies or exception strings containing credential data.
        print('Bootstrap failed. Check token access, network connectivity, commit, and destination.')
        return 1

if __name__ == '__main__':
    raise SystemExit(main())
