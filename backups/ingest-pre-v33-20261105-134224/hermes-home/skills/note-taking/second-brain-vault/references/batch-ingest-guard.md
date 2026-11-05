# Batch ingest through the Windows write guard (proven 2026-08-12)

Proven recipe for ingesting a batch of user-supplied `.md` files (e.g. notes
migrated from an old Obsidian vault) into the LYT-lite vault structure, applied
successfully for 27 files. Read `write-guard-api.md` first for the API basics;
this file is the end-to-end batch recipe plus the ledger contract.

## Current vault structure (2026-08-12)

```text
wiki/
├── pekerjaan/  (market-update, persuratan, data-sbn, derivatif-valas, rapat)
├── ai/         (tools-dan-skill, workflow, prompt, riset)
├── knowledge/  (youtube, sertifikasi, kursus, sumber-lain, catatan)
├── project/    (aktif, selesai, ide, template)
├── pribadi/    (kesehatan, keuangan, keluarga, rencana-dan-ide, refleksi-dan-spiritual)
├── mocs/       (sbn-market-moc, ai-tools-moc, pribadi-moc)
├── index.md · overview.md · log.md · hot.md
assets/         (gambar/attachment, direferensikan via ![[nama]] — resolve by filename)
inbox/          (intake; files stay user-owned, NEVER deleted by ingest)
```

User conventions: ingest = auto-classify into the best domain folder;
ask only when genuinely ambiguous; keep inbox files untouched; sources are
archived via the source ledger (not by copying into `.raw/` for local user notes).

## End-to-end flow

1. **Inventory**: list `inbox/*.md` + `assets/*`; compute SHA-256 per file;
   extract embed refs (`![[name]]`) and verify every referenced image exists in
   `assets/` (missing refs must be reported before apply).
2. **Read every file completely** before classifying (27 files ≈ 145 KB — fine
   to read via `read_file` batches).
3. **Classify**: map each file to `wiki/<folder>/<file>.md`. New subfolders are
   justified when ≥3 notes share a topic (e.g. `derivatif-valas`,
   `refleksi-dan-spiritual`).
4. **Assemble the bundle** (one operation for the whole batch):

```python
op = {
  "schema": "hermes-native-windows-reduced-v1",
  "operation_id": "ingest-batch-27-exobsidian-20260812",  # unique
  "expected_hashes": {path: None | "sha256:<64hex>"},     # None for new files
  "writes": [{"path": "wiki/<folder>/<file>.md", "content": "..."}],
}
```

5. **Page content**: rebuild frontmatter (`type: note`, `title`, `status:
   evergreen`, `created/updated`, `tags`, `sources:`) then append the ORIGINAL
   body (which already contains its H1 — do NOT add another H1).
6. **Guard apply** (run via `subprocess` with `sys.path.insert(0, core)`):
   `inspect_operation` → take `approval_sha256` → `prepare_operation` →
   write files externally (drift-check expected hash before overwrite) →
   `verify_operation` (expect `state: complete`).
7. **Same operation must also update**: `wiki/index.md` (link EVERY new page —
   prevents orphans), `wiki/log.md` (batch entry, frontmatter FIRST — prepending
   an entry above the frontmatter breaks it → `missing_frontmatter`),
   `wiki/hot.md` (refresh), relevant MOC(s), and the source ledger.
8. **Lint** until only acceptable noise remains.

## Source ledger contract (`wiki/meta/ledgers/source-ledger.json`)

Validated by `claude_obsidian/ledgers.py::validate_source_ledger`:

```json
{
  "schema": "claude-obsidian.source-ledger.v1",
  "generated_at": "2026-08-12T00:00:00Z",
  "sources": {
    "src-<stable-id>": {
      "origin": {"kind": "file", "locator": "inbox/<file>.md"},
      "content_kind": "document",
      "authority": "primary",
      "review_status": "unreviewed",
      "title": "<title>",
      "content_sha256": "<64hex of inbox file>",
      "ingested_at": "2026-08-12",
      "pages": ["wiki/<folder>/<file>.md"]
    }
  }
}
```

- Key: `from claude_obsidian.ledgers import stable_source_id;
  stable_source_id("file", locator, sha)` — a free slug fails
  `_safe_ledger_id` AND the canonical-identity check.
- `pages` is required (array of wiki paths); omitting it yields one
  `provenance_errors` per source.
- `review_status: "unreviewed"` avoids the `active` requirement
  (retrieved_at/ingested_at + refresh_due).
- `authority: "primary"` for user's own notes; "secondary"/"official" for
  course/URL-derived content.

## Fix sequence when lint fails after apply

1. `pages_scanned` flat despite new files → files landed outside `wiki/`
   (missing `wiki/` prefix). Move them via a second guarded operation
   (`wiki/<path>`), then delete the wrongly-placed root folders (only safe
   after verifying every file exists at the correct location — they are
   duplicates, and originals remain in `inbox/`).
2. `missing_frontmatter` on log/index → an entry was prepended ABOVE the
   existing frontmatter. Rewrite the page with frontmatter first, entries
   below.
3. `provenance_errors` → rebuild ledger per the contract above.
4. `dead_links`/`stale_index_entries` → link targets don't exist (wrong path)
   — verify against actual file paths, including spaces in filenames.
