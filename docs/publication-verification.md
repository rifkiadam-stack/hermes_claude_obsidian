# Publication and verification boundary

## What this snapshot represents

The repository consolidates the deployed native-Windows core and reusable wiki skills. Publication-only adjustments make script lookup relative to the checkout, remove private operational examples and machine paths, register the supplementary skills, and update packaging tests/documentation. The staging-cleanup adapter also receives security corrections discovered during pre-publication review. Publishing this repository does not install those corrections into an existing Hermes profile.

A separate user vault, profile configuration, credentials, sessions, source captures, runtime indexes, and operation checkpoints are never part of the publication set. Root `.gitignore` excludes common live-vault/profile paths; tests and distribution templates remain synthetic examples.

## Checks before pushing

1. Compare only the authorized product paths and reusable skill/reference files. Do not copy a whole Hermes home or user vault.
2. Scan the complete proposed tracked tree, not only changed Python lines. Inspect historical anecdotes and attachment names in skill references as well as common secret patterns.
3. Preserve upstream/license attribution and use the owner's existing public noreply commit identity.
4. Run `git diff --cached --check`, the Hermes skill/adapter contracts, native guard/BM25 tests, and cleanup provenance regressions against synthetic fixtures.
5. Compare platform-specific failures with the unchanged baseline. On an unprivileged native-Windows host, the upstream lint tests for raw non-UTF-8 filenames and symlink creation can fail for OS limitations; do not claim those passed or weaken the production checks.
6. Freeze the staged tree and obtain an independent final privacy/security review. If it changes afterward, review the changes again.
7. Use an ordinary fast-forward commit/push. Do not push private backups, upstream history, tags, or additional branches as part of this operation.
8. Read back the remote main commit and the published reference document. A local commit or successful command launch alone is not proof of publication.

## Useful test commands

```bash
python -B -m unittest discover -s tests -p 'test_hermes*.py'
python -B -m unittest discover -s tests -p 'test_bm25*.py'
python -B -m unittest discover -s tests -p 'test_second_brain_staging_cleanup.py'
python -B -m unittest discover -s tests -p 'test_contracts.py'
```

See [current implementation](current-implementation.md) for actual lint/BM25 capability boundaries. Session-memory features remain proposals until separately implemented and verified.
