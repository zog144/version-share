# version-share

Version-share lets independent development environments retrieve, review and publish
exact source revisions through authorized GitHub repositories. Both public and
private repositories are supported, subject to the selected token's permissions.
Zog uses it to keep component work in sync without a shared working directory.
It is development tooling, not part of the deployed Zog runtime.

Python 3.10+ library and CLI for source handoffs between isolated ChatGPT Work environments.
Version 0.4.0. No runtime dependencies, Git executable or connector required. Linux is the
supported publication platform (POSIX permissions, fsync and flock). Git is used by one test
as an independent oracle for tree hashing.

## Start

From this source directory:

```sh
PYTHONPATH=src python3 -m zog.version_share --help
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Keep the token outside the source tree. The examples below use a shell function only to
avoid repeating the three global options; the token itself never enters the shell command.

```sh
vs() {
  PYTHONPATH=src python3 -m zog.version_share --token-file /absolute/path/github-token.txt --owner zog144 "$@"
}
vs check-access
vs list-programs
vs retrieve my-program /absolute/path/my-program
vs status /absolute/path/my-program
vs publish /absolute/path/my-program --branch main --message 'Describe the change' --version pass1 --publication-id my-program-pass1
vs list-versions my-program
vs retrieve my-program /absolute/path/review-copy --reference handoffs/pass1
vs compare my-program handoffs/pass1 main
```

Replace `my-program` with an existing repository you are authorized to update.
Edit and test the retrieved source, inspect `status`, and review the diff before `publish`.
For a new component, explicitly run `vs create-program my-program`; creation is private
by default. `list-programs` filters accessible repositories by owner and the `zog-project`
topic, so it is not a complete inventory of all repositories visible to a token. Global
`--json` before the subcommand produces compact machine-readable results. Optional package
installation via `python3 -m pip install .` exposes `version-share` as a command; this may
require fetching setuptools. Running the module directly from a checkout requires `PYTHONPATH=src`.

A working copy records its repository: `publish`, `resume` and `status` use that recorded
identity, not the global owner argument. Use `status` to see it before publishing.

## Source, local state and Python API

`src/zog/version_share/core.py` provides the GitHub client and baseline retrieval;
`transfer.py` verifies archive retrieval; `publication.py` manages durable publication;
`handoffs.py` handles dependency pins and releases; `review.py` supplies endpoint diffs.
`bootstrap.py` is the minimal fresh-environment entry point. Tests live in `tests/`.

Retrieved working copies contain `.version-share/baseline.json` and local publication
records/receipts. Preserve that directory to retain baseline and recovery identities;
do not edit it by hand. These API-backed snapshots are not Git clones. Git is optional
for local diff inspection and does not perform version-share's publication workflow.

Python callers can use `GitHub.from_file(path)`, `check_access`, `list_programs`,
`retrieve_archive`, `status`, `publish` and `resume` from their corresponding modules.
The CLI and Python API share the same safety checks; the CLI additionally redacts its
current token from encoded output. Keep credentials outside any retrieved source tree.
Network access to GitHub's API is required; archive retrieval also needs its download
endpoint. A credential cannot override the environment's network policy.

## Commands

| Command | Purpose |
|---|---|
| `check-access [--program NAME]` | Verify identity and repository read access; reported write permissions are not a live write test |
| `list-programs` | Discover accessible owner repositories with the `zog-project` topic |
| `create-program NAME` | Create a private initialized repository and its discovery topic; repeat calls inspect existing repositories and repair the topic |
| `retrieve NAME DIRECTORY [--reference REF]` | Retrieve a default branch, branch, tag or full commit into a new directory |
| `status DIRECTORY` | List added, modified and deleted paths, exclusions and the latest local publication state |
| `review NAME BEFORE AFTER [--maximum-files N]` | Review exact endpoint snapshots with bounded text diffs, modes, hashes and commit/file links |
| `compare NAME BEFORE AFTER` | Resolve two references and compare their full path/mode/blob manifests |
| `publish DIRECTORY --branch BRANCH --message TEXT [--version NAME] [--publication-id ID] [--maximum-changed-mib N]` | Publish the frozen change set against the verified baseline as one commit; optionally create a named handoff |
| `resume DIRECTORY` | Reconcile/finish the latest recorded attempt, without resnapshotting current source |
| `abandon DIRECTORY` | Discard a preparation only if no branch-reference mutation might have succeeded |
| `list-versions NAME` | List `handoffs/` tags and exact commits |
| `preview-zip ARCHIVE --source-root ROOT` | Inspect files, modes, exclusions and archive checksum without changing a working copy |
| `import-zip NAME ARCHIVE DIRECTORY --source-root ROOT` | Create a fresh local working copy from an explicit ZIP root, bound to the selected repository baseline |
| `handoff DIRECTORY --notes-file FILE` | Write source-controlled notes, reported test results, limitations and dependency pins |
| `release NAME VERSION` | Create or reconcile a GitHub release for an existing handoff, with source ZIP/tar links |
| `retrieve-dependencies DIRECTORY DESTINATION` | Fetch exact dependency commits and safely reuse unchanged copies |
| `project-index` | Resolve discovered default branches into a JSON inventory of exact commits |

`status` and `compare` report file-level changes, including executable/link-mode changes;
use `review` for textual line diffs. See `MIGRATION.md` for the migration and release workflow. Deletions are represented by absence from the complete
new tree. Empty source trees are permitted; inspect the deleted-file list before publishing.
There is no implicit Git ignore support: the exclusions listed below are the complete policy.

## Concurrent work and retry semantics

A publication commits with the retrieved baseline as its single parent. The destination
branch must still equal that baseline, or be a new branch. Updates explicitly use
`force: false`, so competing changes between inspection and update are rejected by GitHub.
The program does not merge, rebase or restart publication against a newer parent.

After a stale-copy rejection, preserve the work on another branch:

```sh
vs publish /absolute/path/my-program --branch review/my-change --message 'Preserve my change' --version review-pass1
```

If a preparation record was already written, first use `abandon`; it refuses when acceptance
is uncertain. A successful abandonment keeps all working files. A completed publication is
not abandoned or rolled back.

Before any Git object upload, version-share streams the complete working tree once to scan
credentials and compute Git blob identities without retaining unchanged contents. It then
compares that manifest with the verified baseline and reopens only content-changing paths to
freeze their bytes. `.version-share/publication.json` records the complete target manifest,
frozen bytes only for content changes, mode-only blob references, explicit deletions,
repository identity, verified baseline tree, target branch, optional handoff, publication ID
and fixed commit author/committer timestamp. Unchanged file contents are not copied into the
durable publication record. Records are atomically replaced with fsync barriers.
One local publication holds a nonblocking process lock. Do not edit the metadata or have
other tools mutate its directory. Source directories must be trusted and quiescent while
snapshotting; there is no atomic snapshot across independently edited files.

On an ambiguous response, run `resume`. It checks the recorded commit against the branch
and its ancestry. If already accepted, it finishes the handoff without a second commit.
If the branch is still at its expected head, it retries the same non-forced update. If the
branch diverged and acceptance cannot be established, it reports uncertainty and blocks.
An operator must inspect that exceptional case; no force/reset recovery command is provided.

Git object uploads are content-addressed. New publications verify the recorded baseline
commit/tree immediately before object creation, then use GitHub's base-tree mechanism so
only content-changing blobs, mode-only references and deletion entries are submitted;
unchanged Git objects are preserved. Publication/status accounting reports
`source_bytes_scanned`, `source_files`, `changed_files`, `content_files` and
`changed_bytes` so a small correction in a large tree is visible as such. Retrying the same fixed tree/commit request does not create a different logical
commit. An interrupted preparation may leave unreachable objects on GitHub; the tool does
not delete them. A completed receipt binds an explicit
publication ID to its original parameters and result, even after another local publication.
Receipts are local to that working copy: they do not provide global cross-chat deduplication.
Use a fresh working copy and inspect immutable handoffs if local state has been lost.

Branch publication and handoff creation are separate remote operations. A branch may be
published while its handoff still needs recovery; this returns `outcome: published` with an
error. `resume` finishes it. Handoff names use lightweight `handoffs/NAME` tags and are never
moved or overwritten by this program. Repository administrators can still change them
outside the tool; enforcement against administrators would require repository rules.

Commit authorship uses the authenticated user's GitHub noreply identity. Commits contain a
`Version-Share-Publication` trailer. The tool does not run tests or assert that caller-supplied
results were verified. Add evidence to a source-controlled document, identifying who ran it.

## Source and credential handling

CLI retrieval now downloads one GitHub ZIP by default and checks every path, mode and blob
hash against the resolved commit's complete tree. `--transport blobs` selects pass 2's
per-blob transfer, useful if archive attributes/LFS substitution cause a mismatch or codeload
is blocked. The Python API exposes `retrieve_archive` explicitly; `retrieve` retains its
original per-blob behavior. Bootstrap retains that small, standalone original path.

Retrieval verifies Git blob hashes, includes hidden files and preserves executable bits and
safe relative symbolic links. Existing destinations are rejected. The baseline manifest is
saved in `.version-share/baseline.json`; old pass-1 copies fetch their missing manifest on demand.
Downloads stage beside the destination. A crash can leave a staging directory or an empty
reserved destination; inspect it and choose a fresh destination before retrying.

Publication excludes `.git`, `.version-share`, `__pycache__`, `.pytest_cache`, `.venv`, Python
bytecode, `.env*` (except `.env.example`/`.env.sample`), PEM/key files, conventional SSH key
files, `github-token.txt`, `.netrc`, `.pypirc`, standard credential filenames and AWS credential
CSV suffixes. Excluded paths are reported. If a baseline already contains excluded paths,
publication refuses to silently delete them: clean that repository separately.

All outgoing file bytes, names and commit text are checked for the supplied token and common
GitHub tokens, AWS access-key IDs and private-key headers. This is a guard, **not a complete
secret detector**. Arbitrary passwords and other secret formats can escape detection.
No outgoing archive or state record contains the supplied token intentionally. Review the
source and `status` before publication. There is no secret-scan bypass option in this pass.

Authenticated API calls contact only `https://api.github.com` and refuse automatic redirects.
Bulk retrieval separately permits HTTPS redirects to `codeload.github.com`, using the short-lived
GitHub download URL without forwarding the Authorization header. URLs and their query strings
are never logged. There is no automatic fallback to another host or transport. Server error
bodies and raw network exceptions are withheld. CLI output redacts the current token. The
Python API returns source/repository metadata unchanged; callers should avoid logging
untrusted contents or credential attributes. No environment-variable token fallback yet.

## Limits

- Publication scans the complete source with no aggregate source-byte ceiling, while retaining
  the 10000-file bound and credential scanning for every publishable path. Changed content is
  limited to 64 MiB by default; set a positive per-publication allowance with
  `--maximum-changed-mib N` (the earlier `--maximum-source-mib` spelling remains an alias).
  The Python `publish` API accepts the corresponding changed-content byte limit. Full-snapshot
  helpers used by other workflows retain their own bounded behavior. Retrieval: 128 MiB and
  10000 tree entries.
- HTTP responses: 32 MiB. Added/modified UTF-8 files are embedded in the delta tree request;
  changed binary blobs upload separately (duplicate binary blobs are uploaded once per attempt).
  Unchanged blobs are reused from the verified baseline tree. Bulk retrieval
  has a 64 MiB compressed / 128 MiB expanded ZIP limit; per-blob retrieval remains available.
- Truncated trees, submodules, unsafe links and reserved metadata paths are rejected.
- Git LFS pointer files remain pointers; large LFS objects are not transferred.
- State records and receipts are retained locally; no retention/reclamation policy yet.
- GET JSON requests retry transient network/502/503/504 failures at most twice, with 1/2-second
  backoff. Recognized rate limits honor Retry-After/reset hints up to 5 seconds; longer waits
  return to the caller. Authentication, missing objects and mutation requests are not retried.
  Archive-byte downloads are single attempts; rerun retrieval after a transfer failure.
  Explicit `resume` continues publications; `release` reconciles by the existing tag.
- No pull-request automation, custom release attachments or automated merges. GitHub's built-in
  source ZIP/tar downloads are provided through releases. `project-index` is an inventory,
  not a claim of cross-program compatibility. Dependency pins are recorded explicitly.
- Git object hashes check consistency, not author authenticity; commits are unsigned.
- Protected branches or workflow-file permissions may reject writes; no rules are bypassed.

## Exit codes and outcomes

Output is JSON, indented by default and compact with `--json`. Machine-mode operational
errors go to stdout; otherwise they go to stderr. Argument-parser errors use standard stderr.

| Code | Meaning |
|---|---|
| 0 | Success |
| 2 | Configuration or command syntax |
| 3 / 4 / 5 | Authentication / forbidden / not found or hidden by token scope |
| 6 / 7 | Network / recognized rate limit |
| 8 / 9 | Conflict / unsupported input or limit |
| 10 / 11 / 12 | Unsafe tree / integrity mismatch / remote protocol error |
| 13 / 14 | Partial completion / local filesystem failure |
| 15 / 16 | Possible secret / uncertain publication |

Publication errors include `outcome`: `not-published`, `published`, or `uncertain`. For
`published`, the branch succeeded even if the handoff or local bookkeeping is incomplete.
For `uncertain`, inspect and resume before starting another attempt. A 404 can mean either
missing repository or insufficient token coverage. A 403 can include secondary rate limiting.

## Access and live verification

Fine-grained GitHub permissions: Administration read/write for repository creation/topics;
Contents read/write for source and handoffs; Metadata read. Owner/repository coverage must
include newly created repositories. Workflow-file changes may require Workflows write.
A token cannot bypass an environment's network restrictions.

See `VALIDATION.md` for performed checks, and `BOOTSTRAP.md` for fresh-chat instructions.
API references: https://docs.github.com/en/rest/git/trees,
https://docs.github.com/en/rest/git/commits, https://docs.github.com/en/rest/git/refs,
https://docs.github.com/en/rest/repos/repos. API version remains pinned to 2022-11-28.

## Review an exact change

```sh
vs review my-program handoffs/pass1 handoffs/pass2 --maximum-files 20
```

`review` resolves both references once, then compares those exact endpoint trees. It does
not use a merge base, infer renames, create a pull request, or execute downloaded source.
Every changed file has old/new modes and blob hashes plus links pinned to the resolved
commits. Text patches use three context lines and indicate missing final newlines. Symbolic
links are reviewed as target text, never followed. Permission-only changes need no blob fetch.

The full changed-file inventory is returned even when patches are omitted. By default up to
20 content changes are examined (configurable 0–100), in added/deleted/modified path order.
UTF-8 text without NUL bytes is diffed up to 64 KiB and 2000 lines per blob; combined patch
output is bounded to 256 KiB. Binary files and size/line/budget omissions have explicit
`diff_status` values. `complete_text_diffs: false` means some changed content is not represented
by a text patch; it does not mean the source comparison failed. `--maximum-files 0` returns
only the inventory and links. Oversized blobs may still be downloaded within the existing
32 MiB HTTP-response limit before being classified. Blob-fetch errors fail the command
rather than silently returning an incomplete success. Only Contents read access is needed.


## Public source and licensing

The reviewed first-party source and documentation in this repository are
available under `BSD-3-Clause OR GPL-3.0-only`. See [LICENSE](LICENSE),
[LICENSES](LICENSES/) and [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).

This repository has fresh public Git history. Previous private commits,
hand-offs, credentials and operational evidence are not included. Previously
recorded commit IDs remain historically distinct from the public source
commit: consumers must deliberately adopt and verify a new source pin.
Historical validation claims are summarized in [VALIDATION.md](VALIDATION.md);
public CI provides reproducible source-level verification.
