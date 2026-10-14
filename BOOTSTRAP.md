# Starting in another ChatGPT Work chat

Give the chat:

1. A token file with access to `zog144/version-share` and the target program.
2. Repository: `zog144/version-share`.
3. The full 40-character version-share commit supplied with the handoff.
4. Target program and the exact commit or `handoffs/NAME` to retrieve.

If this source package is attached, run `PYTHONPATH=src python3 -m zog.version_share` from its root. If only
`bootstrap.py` is available, run:

```sh
python3 bootstrap.py --token-file /absolute/path/github-token.txt --commit FULL_COMMIT --destination /absolute/path/version-share
```

With neither file available, the chat can obtain bootstrap.py using Python's standard
library and GitHub's authenticated Contents API. Substitute the real token-file path and
full pinned commit below. Do not put the token contents in the code or URL.

```python
import base64, hashlib, json, pathlib, urllib.request
TOKEN_FILE = pathlib.Path('/absolute/path/github-token.txt')
COMMIT = 'FULL_40_CHARACTER_COMMIT'
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None
request = urllib.request.Request(
    f'https://api.github.com/repos/zog144/version-share/contents/bootstrap.py?ref={COMMIT}',
    headers={'Authorization': 'Bearer ' + TOKEN_FILE.read_text().strip(),
             'Accept': 'application/vnd.github+json',
             'X-GitHub-Api-Version': '2022-11-28'})
with urllib.request.build_opener(NoRedirect()).open(request, timeout=30) as response:
    item = json.load(response)
assert item['encoding'] == 'base64'
source = base64.b64decode(''.join(item['content'].split()), validate=True)
assert hashlib.sha1(b'blob ' + str(len(source)).encode() + b'\0' + source).hexdigest() == item['sha']
pathlib.Path('bootstrap.py').write_bytes(source)
```

Then run bootstrap.py as above. For tool handoffs with GitHub releases, the release page also provides source ZIP/tar downloads. It downloads core.py from that same pinned commit, verifies
the blob hash, and uses the pinned retrieval implementation to obtain the entire tool.
This trusts the selected GitHub repository and commit. Do not execute code from an unknown
repository. The network must allow api.github.com; no browser or connector is required.

From the retrieved tool directory:

```sh
PYTHONPATH=src python3 -m zog.version_share --token-file /absolute/path/github-token.txt --owner zog144 retrieve PROGRAM /absolute/path/program-copy --reference handoffs/VERSION
```

The downloaded tool is itself a working copy and can publish later tool changes. A fresh
chat should report the resolved source commit before making changes. Review chats should
retrieve a fixed commit or named handoff; implementation chats should use `status` before
publishing. Preserve the `.version-share` directory locally, but never commit/upload it.

After bootstrap, CLI program retrieval uses the faster, Git-tree-verified archive transport.
If the environment cannot reach codeload.github.com, select `--transport blobs` explicitly.
Do not forward the GitHub Authorization header when following a download redirect.

For review, resolve and inspect the proposed handoff against its starting version:

```sh
PYTHONPATH=src python3 -m zog.version_share --token-file /absolute/path/github-token.txt --owner zog144 review PROGRAM handoffs/BASE handoffs/PROPOSED
```

Check every file record's `diff_status`; binaries and omitted large patches require separate
inspection. The command reports exact source commit identifiers suitable for a review handoff.
