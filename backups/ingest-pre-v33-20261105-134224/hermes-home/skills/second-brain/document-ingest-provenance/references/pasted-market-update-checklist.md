# Pasted Market Update ingest checklist

Use this checklist for a user-pasted daily Market Update:

1. Treat the message as one bounded authored source and preserve its complete wording in `.raw/MU YYYYMMDD.md`.
2. Create `wiki/pekerjaan/market-update/market-update-YYYY-MM-DD.md` with complete frontmatter, a concise SUN-focused synthesis, and the complete source under `## Sumber lengkap`.
3. Add a short introductory sentence after `## Sumber lengkap` before the source begins. A heading immediately followed by another heading can trigger a false-looking `empty_sections` finding.
4. Preserve conflicting snapshots across sections (oil, FX, UST, domestic data) and identify them rather than silently reconciling them.
5. Prioritize SUN direction, end-day series moves, IHSG, rupiah, PLTE volume, and foreign net buy/sell in the synthesis; summarize only SUN-relevant global drivers.
6. Apply through the native Windows guarded lifecycle, then verify raw/page/ledger/manifest hashes, lint, BM25, and released `write.lock`.

The canonical synthesis is a summary, not a replacement for the complete source.
