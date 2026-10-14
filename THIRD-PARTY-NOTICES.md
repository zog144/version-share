# version-share public source and dependency notices

The original first-party Python code, bootstrap program, tests and documentation
included in this repository are licensed, at your option, under
`BSD-3-Clause OR GPL-3.0-only`. See [LICENSE](LICENSE) and the full texts
in [LICENSES](LICENSES/).

The component has no declared runtime third-party dependencies. Setuptools
(for source package construction) and Git (an optional independent tree-hash
test oracle) are obtained separately with their own licenses. Other tooling
used to consume its API is also subject to its own grants and notices.

This new public source history deliberately excludes the original private
history, private handoff records, access tokens, individual operational
verification files and historical workflow artifacts. Old commit identities
remain provenance references, not commits in this public repository.

The `version-share` development package is not approved as a separate PyPI
distribution; the public Zog Python distribution is assembled by release-build
under the project name `zog`.
