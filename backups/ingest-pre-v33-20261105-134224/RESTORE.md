# Legacy ingest rollback snapshot

This is a backup, not an installer. Product files and hermes-home files retain their original bytes. MANIFEST.json records per-file SHA-256.

Before any restore: stop the affected operation, inspect actual lock/checkpoint state, preserve new state, verify all snapshot hashes and obtain separately scoped restore authority. Restore only registered product/skill/helper paths, never a user vault, runtime credentials or another profile. Restart/reload decisions are separate; do not kill the gateway from inside its own session.

The production vault, credential/config files, cron, memories and databases are intentionally NOT part of this GitHub payload. Their preservation is not claimed by this code/skill snapshot.
