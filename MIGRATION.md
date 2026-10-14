# Migration, handoffs, releases and adoption

Run from the version-share source directory. Keep your token outside every source tree.
Examples use this convenience function:

```sh
vs() {
  PYTHONPATH=src python3 -m zog.version_share --token-file /absolute/path/github-token.txt --owner zog144 "$@"
}
```

## Import an existing ZIP

First identify the authoritative archive and its intended repository. A filename alone does
not prove it is the newest implementation. Inspect its handoff and validation records. Some
archives contain multiple programs and evidence bundles; decide whether to preserve that
bundle or select a narrower root before import. Do not infer dependency versions from similar
names or silently discard supporting files.

```sh
PYTHONPATH=src python3 -m zog.version_share preview-zip /absolute/path/source.zip --source-root top-level-folder
vs create-program PROGRAM
vs import-zip PROGRAM /absolute/path/source.zip /absolute/path/program-copy --source-root top-level-folder
vs status /absolute/path/program-copy
```

`--source-root .` explicitly selects the ZIP root. A source root is mandatory; no wrapper is
silently stripped. The preview works without a token, or can take `--token-file` to include
an exact-token scan. Import uses the same exclusions and scans as publication. Both report
exclusions. ZIP traversal, duplicates, file/directory conflicts, encryption, special files,
unsafe symbolic links and excessive expansion are rejected.

Import creates a new local directory and does not upload source. It binds the source to the
selected repository/default branch (or `--reference REF`) for later publication. Status shows
any files that publication would delete from that baseline. Existing destination directories
are never overwritten. The original ZIP is untouched. Its name, SHA-256, selected source
root, exclusions and file manifest are stored locally for provenance.

The credential scan is not a full secret detector. ZIP import scans selected members but
does not recursively unpack nested archives; inspect embedded evidence archives separately
before publishing them. Consider deployed configuration and evidence carefully when moving
private archives to a new service. Publication requires authorization for that payload and
destination, even when the destination repository is private.

## Add handoff evidence and dependency pins

Prepare notes as a text file. Optional test results use this JSON format:

```json
[
  {"command": "python3 -m unittest discover -s tests -q", "result": "54 tests passed"}
]
```

Use only results actually observed or explicitly attributed to an earlier report. The tool
labels every supplied result `caller-reported`; it does not execute tests or claim it ran them.

```sh
vs handoff /absolute/path/program-copy --notes-file /absolute/path/notes.md --test-results-file /absolute/path/tests.json --dependency OWNER/DEPENDENCY=FULL_40_CHARACTER_COMMIT --limitation 'No live-host acceptance run in this pass'
```

Omit `--dependency` or repeat it for multiple dependencies. Only full commit identifiers are
accepted, and each is checked against the specified repository. Branch names are not pins.
Notes, test evidence, limitations and import provenance are written to
`version-share-handoff.json`, which becomes part of the source commit. These describe the
upcoming publication, not a mutable page attached to some other source version.

## Publish and release

```sh
vs status /absolute/path/program-copy
vs publish /absolute/path/program-copy --branch main --message 'Import the selected implementation' --version import-pass1 --publication-id PROGRAM-import-pass1
vs release PROGRAM import-pass1
```

Publication keeps pass 2's frozen-source, baseline and non-forced update protections. A
release requires the existing `handoffs/import-pass1` tag and reads its handoff metadata at
that exact commit. Release creation never changes a tag or edits an existing release.
Repeating it reconciles a lost accepted response; conflicting existing release metadata
blocks instead of being replaced. GitHub supplies the source ZIP/tar downloads automatically;
custom binary assets are not uploaded. Releases are not marked latest automatically.

## Retrieve for review or integration

```sh
vs retrieve PROGRAM /absolute/path/review-copy --reference handoffs/import-pass1
vs retrieve-dependencies /absolute/path/review-copy /absolute/path/dependencies
vs project-index
vs review PROGRAM handoffs/previous handoffs/import-pass1
```

Retrieval defaults to one bulk ZIP download, verified against the exact Git tree. Use
`--transport blobs` when needed. Dependency retrieval can be repeated: unchanged copies at
exactly the recorded commit are reused, and modified or mismatched copies are rejected.
A failed later dependency does not remove earlier completed copies. Retry the same command
once connectivity is restored. Dependencies are direct pins; recursive dependency resolution
and cyclic graph handling are not implemented.

The project index resolves each discovered repository's default branch to a commit. It does
not assert those commits were tested together. Record real compatibility requirements using
explicit dependency pins and evidence in a handoff.

## Adoption sequence

1. Prove source retrieval and publication in a fresh chat (the user confirmed this for pass 2).
2. Import one explicitly authorized real handoff, preserve provenance, and verify its source
   manifest after downloading it again.
3. Use exact handoffs for the implementation/review/revision cycle.
4. Identify each remaining program's authoritative source and import it deliberately.

Pull-request automation remains optional future work; it would require additional token
permissions. Program-wide migration and claims of compatibility require actual source and
test evidence, not just a successful GitHub connection.
