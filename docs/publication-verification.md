# Publication verification record

This distribution candidate is a sanitized snapshot based on public baseline `2cdd106`. Its selected implementation files were copied into the snapshot without importing production Git history.

## Candidate checks

- Compared nine designated implementation/dependency files with the approved production source revision: **9/9 byte-identical** (size and SHA-256 comparison).
- Sanitized-tree scan: **271 text files**, 11 private patterns held outside this repository, **0 private-pattern hits** and **0 generic local-path/credential-pattern hits**.
- Relevant repository, unit, and MCP black-box acceptance checks: **114 passed, 2 skipped, 41 subtests passed**. The skipped checks are platform-limited capability verifiers on native Windows; the MCP black-box suite ran with synthetic fixtures and passed.
- Release-builder and artifact-auditor tests: **38 passed, 2 skipped, 4 subtests passed**, including a regression for Windows text-mode EOF handling in ZIP files.
- MCP test subprocesses now exclude environment variables whose names indicate credentials; synthetic tests verify the filter.

## Release procedure and state

1. Keep private sanitizer patterns outside the repository; repository contracts use only general patterns and synthetic test values.
2. Compare the exact payload and repeat the sanitizer scan after any edits.
3. Build the deterministic ZIP from a clean candidate worktree and audit it. The verified archive contains **268 files**; its generated `RELEASE_MANIFEST.json` and `SHA256SUMS` are the authoritative release metadata. The builder does not stage, commit, tag, push, or publish.
4. Refresh the root-level sidecar copies from the audited archive; verify exact byte equality before committing them.
5. Review the final Git diff and sidecar metadata before any publication.

The sanitized source snapshot, relevant tests, release build, and archive audit have been verified. The artifact is not published; push or publication remains a separate action.
