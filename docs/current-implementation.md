# Current implementation reference

This source snapshot consolidates the locally deployed core, native Windows adapters, and active wiki workflow skills. Published copies remove private machine paths and user-specific prose; native scripts locate the core relative to the checkout. It is a source snapshot, not a new generated upstream release artifact. Root `RELEASE_MANIFEST.json` and `SHA256SUMS` retain their historical release-artifact role and do not attest this working source tree.

## Entry points

| Concern | Source |
|---|---|
| Deterministic lint | `claude_obsidian/lint_engine.py` |
| Source/claim ledger validation | `claude_obsidian/ledgers.py` |
| Native write lifecycle and recovery | `claude_obsidian/hermes_windows_write.py` |
| Native large-index writer | `claude_obsidian/hermes_windows_bm25.py` |
| Native BM25 provisioning | `scripts/bm25_provision_native.py` |
| Verified inbox/Clippings cleanup | `scripts/second_brain_staging_cleanup.py` |
| Page collection, parsing, chunking | `scripts/contextual-prefix.py` |
| Lexical scoring/index validation | `scripts/bm25-index.py` |
| Result validation and deduplication | `scripts/retrieve.py` |

## Lint

Required page-frontmatter keys: `title`, `type`, `status`, `created`, `updated`, `tags`. The page check validates presence, not a complete YAML value schema. Aliases assist link resolution; `address` is not required by lint. Ledger contracts are validated separately.

The current page-check scope is `wiki/`. Files elsewhere can be link targets, but their outgoing links/frontmatter/orphan status are not automatically checked as wiki pages. The parser understands wikilinks, embeds, local Markdown links, aliases, heading/block fragments, and code masking. It reports broken/ambiguous links, duplicate basenames, orphans, missing frontmatter, empty sections, and problematic index entries. It does not mandate section names, H1 count, or semantic agreement between sections.

Lint is read-only. It has no `--fix` and no section-specific `Log` exclusion. Agent repairs are separate, explicitly scoped guarded operations. A target allowlist is not a section exclusion. Frontmatter links are masked from the link graph; strikethrough does not exclude a link.

## Retrieval

The collector currently scans `wiki/**/*.md`. Index and retrieval validators also require source pages under `wiki/`. Native provisioning reuses this collector and performs bounded reads. Prefixes are synthetic/local by default.

BM25 indexes chunks, not separate session-main/history documents. Retrieval deduplicates candidates by page address/path. Current query interfaces expose candidate counts and optional reranking, not document-type filters or per-document history weights. Adding `type: sesi` or `jenis: sesi` alone does not enable filtering; the prefix parser extracts `address` and `title`, not arbitrary metadata.

## Session-memory proposal: NOT IMPLEMENTED

No `memori-sesi` skill, profile-to-vault mapping, `Sesi/` folder creation, session ingestion hook, split main/history document model, history filter, or history downweighting is activated by this snapshot. Those require a separately approved bounded extension across collection, validation, metadata propagation, ranking/filtering, result deduplication, and section-aware reading. Do not infer support from documentation examples.

## Ingest authority

`skills/wiki-ingest/SKILL.md` owns mode selection: verbatim, rapikan, or explicitly requested transcript synthesis. Historical synthesis recipes do not override source-fidelity requirements. Native helper skills supplement transaction safety and verification; they do not activate unrelated repairs or extra review loops.

## Publication boundary

Included: product code, regression tests, reusable skills/references, public examples, and technical documentation.

Excluded: actual vault notes/raw captures, provenance ledgers from user vaults, indexes/chunks, sessions/transcripts, uploaded documents, credentials, profile configs, messaging identifiers, operational reports, and backup branches. Author/license attribution remains intact.
