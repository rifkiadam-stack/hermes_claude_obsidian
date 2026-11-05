---
name: second-brain-vault
description: "Second Brain vault ops: guarded writes, lint, BM25."
version: 1.0.0
author: Hermes Agent (port of AgriciDaniel/claude-obsidian)
license: MIT
platforms: [windows]
metadata:
  hermes:
    tags: [second-brain, obsidian, wiki, vault, bm25, knowledge]
    related_skills: [wiki, wiki-query, wiki-lint, wiki-retrieve, save, obsidian]
---

# Second Brain vault operations

## When to Use

Use when working with the user's external Obsidian Second Brain vault managed by
the Hermes port of `AgriciDaniel/claude-obsidian`: saving/ingesting/querying
notes, running lint, building BM25 retrieval, or maintaining the vault
structure. The vault lives at `G:/My Drive/hermes_obsidian`; the 15 workflow
skills (`wiki`, `save`, `wiki-ingest`, `wiki-query`, `wiki-lint`,
`wiki-retrieve`, `wiki-mode`, `wiki-fold`, `autoresearch`, `defuddle`,
`wiki-cli`, `obsidian-markdown`, `obsidian-bases`, `canvas`, `think`) are
installed under `skills/second-brain/` and route here.

## Environment

- `HERMES_OBSIDIAN_VAULT` — explicit vault path (set in Hermes `.env`, forward
  slashes). Core scripts still honor legacy `CLAUDE_OBSIDIAN_VAULT`; both work.
- `HERMES_CLAUDE_OBSIDIAN_CORE` — product root with `scripts/claude-obsidian.py`
  (`C:/Users/rahmazaki.adam/AppData/Local/hermes/components/claude-obsidian-core`).
- Never hard-code these paths inside skills; read them from env.

## User-directed filing routes

For a user's stable, explicitly requested destination for a recurring source class, keep the route explicit and consult it before ingest rather than creating a new top-level taxonomy each time. Adam's YouTube Islamic lecture/kajian material belongs under **Pengajian** in `wiki/pribadi/refleksi-dan-spiritual/`; see `references/user-filing-routes.md`. If Adam says “LLM Wiki” but identifies the existing Obsidian vault, use the managed Obsidian vault; do not create a separate Karpathy-format wiki.

## The one rule that governs every mutation

The upstream POSIX transaction core **refuses apply on native Windows**
(`UNSUPPORTED_PLATFORM`: directory-descriptor confinement requires
WSL/Linux). Read-only CLI commands (dry-runs, `lint`, `mode get`, BM25 build)
work natively. **Every vault write must go through the reduced-guarantee
guard** in `claude_obsidian/hermes_windows_write.py`:

```text
inspect_operation(vault, operation)      # validates paths/hashes -> approval
prepare_operation(vault, operation, approval)   # recheck + before-images + lock
<write files with Hermes file tools>
verify_operation(vault, operation, approval)    # after-hash verify + release lock
rollback_operation(vault, operation, approval)  # only when current in {before, after}
```

The operation is `{schema: hermes-native-windows-reduced-v1, operation_id,
expected_hashes, writes: [{path, content}]}` — expected_hashes = current
SHA-256 for existing targets, `None` for new files. See
`references/write-guard-api.md` for the full API, checkpoint layout, and the
init/adopt plan-conversion recipe.

## Init / adopt an existing vault (no WSL needed)

1. `python -B scripts/claude-obsidian.py init|adopt <vault> --generated-at <ISO> --operation-id <id>` (dry-run).
2. The dry-run JSON's `operation` (schema `claude-obsidian.transaction.v1`,
   `writes[{content, mode, path, sha256}]`, `expected_hashes`) converts
   **directly** into the guard's operation — drop `mode`/`sha256`, keep
   `path`+`content`.
3. Guard apply: inspect → prepare → write → verify.
4. `git config core.autocrlf false` if you init a local Git checkpoint —
   autocrlf=true materializes CRLF and silently breaks every content hash.

## Lint (read-only, native)

```bash
python -B scripts/claude-obsidian.py lint --vault "G:/My Drive/hermes_obsidian" --format json
```

Report is per-category (NOT a `findings` key). Blocking categories:
`dead_links`, `ambiguous_targets`, `missing_frontmatter`,
`stale_index_entries`, `read_errors`, `configuration_errors`,
`provenance_errors`. `issues_found` counts everything including informational
orphans.

## Retrieval (BM25)

`scripts/bm25-index.py` runs in path-based mode on Windows (no dirfd needed):
`configure_vault(str(vault))` → `build_index()` → `write_index(index)` →
`query(text, top_k)`. Chunk records must live at
`.vault-meta/chunks/<address>/chunk-<idx>.json` with the exact upstream schema
— see `references/windows-bm25.md`. Stale chunks (page changed) are skipped at
build time, which can silently empty query results.

## Pitfalls (all hit in production)

- **Write paths MUST start with `wiki/`** — the guard validates path SAFETY but
  NOT location. `pekerjaan/x.md` passes inspect and lands in the vault root;
  the write "succeeds" but lint `pages_scanned` stays flat, index links go
  dead, and the pages are invisible to the wiki scan. Always
  `wiki/<folder>/<file>.md`.
- **`inspect_operation` approval key is `approval_sha256`** (not
  `approved_plan_sha256`), and expected hashes are `sha256:<64-hex>` WITH the
  prefix (`_HASH_RE = ^sha256:[0-9a-f]{64}$`). Bare hex is rejected.
- **Duplicate H1 on page rewrite** — if the existing body already has
  `# Title`, appending another H1 creates H1 ganging: lint reports each H1 as
  an `empty_sections` hit. Strip existing H1 lines from body before emitting
  a fresh one.
- **Source ledger schema** — keys must be `stable_source_id(kind, locator,
  sha)` from `claude_obsidian.ledgers` (NOT free slugs); each record needs
  `origin{kind,locator}`, `content_kind`, `authority`, `review_status`,
  `title`, `content_sha256`, and **`pages`** (array of wiki paths that use the
  source). Missing `pages` → one `provenance_errors` per record. See
  `references/batch-ingest-guard.md`.
- **Dual intake staging** — durable ingest checks both `inbox/` and `Clippings/` (Obsidian Web Clipper output). Both are user-owned staging and must remain intact unless the user explicitly requests cleanup. “Already processed” requires hash comparison against `.raw/.manifest.json`, the source ledger, and the canonical page—not filename presence alone. A chat-pasted source can be ingested directly only when its full text is captured into `.raw/` and its provenance is recorded.
- **External vs local media** — preserve external source/image URLs as URLs unless the user explicitly requests a download. Only local image files actually referenced by Markdown enter the contextual rename workflow; rename them deterministically, rewrite embeds in the same guarded operation, and verify no missing image links or unused assets after apply.
- **Clipping normalization** — preserve the original clipping payload byte-for-byte in `.raw/`, while normalizing clipping frontmatter into the canonical wiki page. Keep the clipping’s source URL in frontmatter/provenance and link the canonical page from its domain index/MOC.
- **Batch ingest orphans** — every new page must be linked from `index.md` (or a MOC) in the same operation, or lint flags orphans.
- **`empty_sections` on user notes may be pre-existing** — consecutive
  same-level headings (`### A.` then `### 1.` with no body) render fine in
  Obsidian; only edit with explicit user consent.
- **Rollback refuses unknown content** — by design. Rollback only restores when
  the current file matches `before_sha256` or `after_sha256`; any other content
  raises `ConcurrentDriftError` and keeps the lock. Restore the known after
  content first, then rollback.
- **git autocrlf** — see above; byte stability is mandatory for hashing.
- **printf mangles backslashes** — `printf '...C:\Users...'` interprets `\U`,
  `\M` escapes and corrupts lines (hit while editing `.env`). Always write env
  values with **forward slashes** and edit files via Python, not shell printf.
- **Concurrent Obsidian edits** — Obsidian ignores the cooperative lock; avoid
  editing targets while a guard operation is prepared. Drift aborts instead of
  overwriting.
- **`.gitignore` is case-insensitive on Windows** — a pattern like `WIKI*.md`
  also ignores `wiki-*.md`; check `git check-ignore -v` before renaming files
  into a new directory.
- **`contracts --verify` reports degraded** on native Windows for core
  capabilities whose verifiers mutate a vault — documented platform limitation
  (`docs/windows-wsl.md`), not a port regression.
- **Stuck `write.lock` after a refused rollback** — investigate the drift
  first; a lock is released only by a successful verify/rollback or manual
  cleanup after review.

## Verification

`scripts/vault_health_check.py` probes env, guard import, lint, and BM25 index
freshness in one run. Run it after any vault maintenance.

## References

- `references/write-guard-api.md` — guard API, operation schema, checkpoint
  layout, init/adopt plan conversion.
- `references/batch-ingest-guard.md` — end-to-end batch ingest recipe, source
  ledger contract, fix sequence for lint failures (proven on 27-file batch).
- `references/windows-bm25.md` — BM25 path-based mode, chunk record schema,
  staleness rules.
