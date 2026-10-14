# Public validation and historical acceptance boundaries

This document separates **historical private-source verification reports**
from reproducible verification of the current public repository. The former
cannot be treated as a fresh run against the public commit.

## Public, reproducible checks

The public GitHub Actions workflow runs Python 3.10 and 3.13 source-level
unittest discovery, compilation and the `version-share --help` entry point.
A separate Python 3.11 package job builds a wheel and source archive and
checks namespace, licensing and source-file boundaries. See the workflow
runs for the exact public commit and whether each job passed.

The source tests cover Git tree/blob identities, ZIP retrieval, validation
and path safety, local publication state and recovery, competing writers,
non-forced branch updates, retry/uncertainty semantics, version handoffs,
frozen changes, GitHub API and review diff boundaries. Mocked GitHub
responses and synthetic ZIPs are not live GitHub acceptance.

## Historical acceptance summaries — not rerun for this public commit

Private-development validation reported 39 offline tests in pass 2,
54 in pass 3 and 62 in pass 4 (September 2026). Additional historical
live tests covered source publication/retrieval, competing writer rejection,
recovery after ambiguous accepted responses, diff review, release creation
and pinned dependency reuse. These were performed against private-source
revisions and private synthetic test repositories, not this public commit.

Detailed historical evidence remains in maintainers' private records.
The exact old private commits, test-repository identifiers and private
evidence links are intentionally omitted from this public document.
The new public Git revision is not an alias for any earlier private
commit, tag or test receipt.

## Outstanding gates

Public CI is not a live cross-environment Work invocation. A fresh-chat
GitHub round-trip on the public commit, authenticated publish/recovery
and independently reproduced integration with downstream Zog components
remain separate acceptance work. The aggregate Zog PyPI release is
owned by release-build.
