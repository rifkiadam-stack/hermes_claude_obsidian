# BM25 retrieval on native Windows — path-based mode

`scripts/bm25-index.py` uses directory-descriptor locking (`O_DIRECTORY`,
`dir_fd`, `MutationLock`) for its fd-based path, but **falls back to plain
path-based mode when called with no fds** — which works on native Windows.

## Working invocation (from Python)

```python
import importlib.util, sys
from pathlib import Path
REPO = Path(os.environ["HERMES_CLAUDE_OBSIDIAN_CORE"])
sys.path.insert(0, str(REPO))
spec = importlib.util.spec_from_file_location("bm25idx", REPO / "scripts" / "bm25-index.py")
bm25 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bm25)

assert bm25.configure_vault(str(vault))      # resolves vault explicitly
index = bm25.build_index()                    # skips stale chunks
bm25.write_index(index)                       # atomic tmp + os.replace
results = bm25.query("query terms", top_k=5)  # ranked [{chunk_id, score, path, ...}]
```

`configure_vault()` honors `CLAUDE_OBSIDIAN_VAULT` env and `--vault`; it does
NOT know `HERMES_OBSIDIAN_VAULT` — pass the vault explicitly or set the legacy
env var. A vault must have a sentinel (`.claude-obsidian.json` or `.obsidian/`)
or it fails with `VAULT_SENTINEL_MISSING`.

## Chunk record schema (exact)

Stored at `.vault-meta/chunks/<page_address>/chunk-<chunk_index>.json`:

```json
{
  "page_address": "c-000001",
  "chunk_index": 0,
  "raw_text": "paragraph text",
  "contextualized_text": "same as raw for local synthetic prefix",
  "body_hash": "sha256:<hex of raw_text utf-8>",
  "page_path": "wiki/example.md",
  "page_body_hash": "sha256:<hex of page FILE BYTES>"
}
```

`page_path` must start with `wiki/` and be vault-relative. `body_hash` must
hash exactly `raw_text`; `page_body_hash` must hash the page **bytes as read
with `.read_bytes()`** (not text-decoded).

## Staleness (fail-closed behavior)

`discover_chunks()` skips any chunk whose `page_body_hash` no longer matches
the live page file — "source page changed". Skipped chunks contribute no terms,
so a query can silently return **0 results** even though the vault has the
text. Root causes seen in production:

- Page edited after chunks were written → rebuild chunks.
- **git autocrlf**: `core.autocrlf=true` (Windows default) materializes CRLF on
  `git checkout`, changing page bytes → every chunk for that page goes stale.
  Fix: `git config core.autocrlf false` in the vault repo before committing
  (byte stability is mandatory for content hashing).

## Index output

`build_index()` returns `{avg_dl, doc_count, docs, params, schema_version,
updated_at, vocab}` (no `postings` key at top level). `write_index()` returns
None in path-based mode (writes `.vault-meta/bm25/index.json` atomically).
