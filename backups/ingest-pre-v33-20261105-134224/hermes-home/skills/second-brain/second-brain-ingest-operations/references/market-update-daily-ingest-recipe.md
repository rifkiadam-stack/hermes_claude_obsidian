# Daily Market Update ingest — proven recipe

Validated across consecutive daily ingests (2026-09-10, 11, 14, 15, 16, 17).
Each run: guard `complete`, raw SHA-256 matching ledger + manifest, lint 0
issues, `write.lock` released, BM25 refreshed. Use this as the default path for
every pasted daily MU.

## Shape of the work

Three artefacts, one guarded transaction:

| Path | Role |
|---|---|
| `<hermes>/docs/mu_YYYYMMDD_source.md` | staging copy of the pasted text (outside vault) |
| `.raw/MU YYYYMMDD.md` | immutable create-only archive inside the vault |
| `wiki/pekerjaan/market-update/market-update-YYYY-MM-DD.md` | canonical page |

Plus, in the same operation: the Market Update MOC, `wiki/meta/ledgers/source-ledger.json`,
`.raw/.manifest.json`, `wiki/log.md`, `wiki/hot.md`.

## Step 1 — stage the source verbatim

Write the pasted text unchanged to `<hermes>/docs/mu_YYYYMMDD_source.md`. Do not
paraphrase, reorder, or "fix" the source here — it becomes the archived raw
payload and its SHA-256 anchors provenance. Preserve every quoted figure and
every intraday snapshot exactly as received.

## Step 2 — clone the previous day's script, do not author from scratch

The single biggest time-saver: copy the last run's script and re-point it.

```bash
cp <hermes>/scripts/apply_mu_<PREV>_ingest.py \
   <hermes>/scripts/apply_mu_<CURR>_ingest.py
```

Then replace, in this order:

1. **Both date token forms.** `YYYYMMDD` and `YYYY-MM-DD` appear in paths, the
   raw locator, the page frontmatter, ledger/manifest `ingested_at`/`archived_at`,
   the MOC link, the log heading, and the `operation_id` prefix. Do a
   `replace_all` pass for each form — missing one silently produces a page whose
   frontmatter disagrees with its filename.
2. **The `summary` string** — rewrite for the new day's actual direction and
   numbers.
3. **The page body** — the `## Faktor pasar yang dilaporkan` bullets, the
   `## End day SUN dan pasar domestik` table, and the
   `## Catatan konsistensi sumber` paragraph.
4. **The `hot` line** — one sentence, must reflect the new day.
5. **Verify** the edit landed with the syntax check that `write_file`/`patch`
   reports (`lint: ok`) before running.

Escaping matters: the page is an f-string, so literal braces and any `{}` in the
prose must be doubled. The final `{text.rstrip()}` interpolation is what appends
the full source.

## Step 3 — keep the page skeleton that passes lint

This section order has produced 0 lint findings repeatedly:

```
frontmatter (type, title, status, created, updated, date, tags)
# Market Update YYYY-MM-DD
Sumber: [[.raw/MU YYYYMMDD.md]]
## Ringkasan SUN          <- one dense paragraph, direction first
## Faktor pasar yang dilaporkan
## End day SUN dan pasar domestik   <- before/after table + domestic bullets
## Catatan konsistensi sumber
## Sumber lengkap          <- "Teks sumber berikut dipertahankan..." + {text}
```

Rules that keep it clean:

- Exactly one H1. Do not add a second heading level that leaves a parent empty.
- Complete frontmatter — `created` and `updated` are required or lint flags
  `missing_frontmatter` even when the delimiters exist.
- Every internal link must resolve. The `.raw/MU YYYYMMDD.md` wikilink is valid
  because the same transaction creates that file.
- `wiki/log.md` entries prepend **after** the frontmatter, inserted on the
  `Newest completed operations appear first.` marker.

## Step 4 — check arithmetic with explicit units and source scale

Before describing a reported movement, compare supplied start/end values and reported change using a tool. Keep scale and unit explicit: a SUN yield of 7.02 to 7.28 differs by 0.26 percentage point = 26 bps; an IHSG move from 5,863.78 to 5,185.11 is 678.67 index points, reported rounded to 679. Do not rescale index levels as decimals or mix percent changes with points/basis points. Preserve source figures and wording; use the calculation only to classify the report as consistent after rounding or as a discrepancy to note. Never use a derived calculation to silently edit the immutable raw or canonical transcription.

## Step 5 — the consistency note is mandatory

Daily MU sources routinely carry several different observation times for the
same instrument (DXY "up 0.5%" in one section and "relatif stabil" in another;
JPY quoted at three levels; the same yield given both at a close and in the
afternoon update). **Never reconcile these into one number.** List the
conflicting readings explicitly under `## Catatan konsistensi sumber` and state
that they are preserved as source observations rather than reconciled
inferentially. This is both the user's standing requirement and the honest
handling.

## Step 6 — run, then verify with real numbers

```bash
python <hermes>/scripts/apply_mu_<CURR>_ingest.py
```

Expect a JSON result with `"status": "complete"` and an `operation_id`. Then
verify provenance, lint, and the index in one pass:

```bash
python - <<'PY'
import hashlib, json
from pathlib import Path
V = Path(r'G:\My Drive\hermes_obsidian')
raw, page = V/'.raw/MU YYYYMMDD.md', V/'wiki/pekerjaan/market-update/market-update-YYYY-MM-DD.md'
L = json.loads((V/'wiki/meta/ledgers/source-ledger.json').read_text(encoding='utf-8'))
M = json.loads((V/'.raw/.manifest.json').read_text(encoding='utf-8'))
d = hashlib.sha256(raw.read_bytes()).hexdigest()
recs = [{'sid': s, 'ledger_sha': r.get('content_sha256'),
         'manifest': M.get('sources', {}).get(s)}
        for s, r in L.get('sources', {}).items()
        if r.get('origin', {}).get('locator') == '.raw/MU YYYYMMDD.md']
print(json.dumps({'raw_bytes': raw.stat().st_size, 'page_bytes': page.stat().st_size,
                  'actual_sha': d, 'records': recs,
                  'write_lock': (V/'write.lock').exists()}, ensure_ascii=False))
PY
```

Then lint and re-index, reporting the *actual* counts:

```bash
python "$CORE/scripts/claude-obsidian.py" lint --vault "$VAULT" \
  | python -c "import sys,json;d=json.load(sys.stdin);print(json.dumps({'issues':d['summary']['issues_found'],'pages':d['summary']['pages_scanned'],'links':d['summary']['links_scanned'],'dead_links':len(d['dead_links']),'provenance_errors':len(d['provenance_errors']),'missing_frontmatter':len(d['missing_frontmatter']),'empty_sections':len(d['empty_sections'])}))"
python "$CORE/../bm25_provision_native.py" --vault "$VAULT"
```

Success looks like: raw SHA == ledger `content_sha256` == manifest `sha256`,
`write_lock` false, `issues: 0`, and BM25 reporting changed chunks with a rising
doc count. Report those numbers rather than asserting "done".

## Step 7 — separate source date from ingest/audit date; inspect before apply

For a dated MU, keep three notions distinct: the date stated by the source,
the actual date/time of ingestion, and the validator's audit date. Do not
backdate `created`, `ingested_at`, or `archived_at` merely to silence lint.
Use the actual local date for the ingest metadata; pass that explicit date to
`lint --as-of YYYY-MM-DD` when the default UTC audit date is still the previous
calendar day. This makes the timezone assumption explicit and prevents a
correct local-day ingest from being misreported as a provenance defect.

When the native transaction helper supports a saved plan, build it in plan-only
mode, inspect the exact changed paths, source-byte count, summary, and approval
hash, then apply that same saved operation. On apply, re-inspect the approval
hash and fail closed if the vault preconditions changed. Do not reconstruct a
new operation between review and apply, because regenerated timestamps or IDs
can change its approval hash. A clear, direct user request to ingest authorizes
the requested scope; still show the bounded preview before applying.

After provisioning BM25, run a focused retrieval probe using distinctive
source terms and verify the target date's page appears at the top of results.
Also check that both the vault transaction lock and BM25 index lock/stage files
are absent. Run staging cleanup discovery for eligible intake artifacts, but
never delete `.raw/`; only apply cleanup when discovery returns verified items
and the user-requested cleanup scope authorizes it.

## Pitfall — do not build the heredoc inside `execute_code`

Wrapping a `python - <<'PY' … PY` heredoc inside an `execute_code` code string
fails with:

```
SyntaxError: unterminated triple-quoted string literal (detected at line N)
```

This costs a round-trip and looks like a vault problem when it is a quoting
problem. The verification script above is a shell heredoc — **run it through
`terminal` directly.** Same for any multi-line Python that mixes Windows paths
with quoting. Keep `execute_code` for scripts that import `hermes_tools` and use
native Python strings, not for embedding shell heredocs.

## Pitfall — one failing verification call is not a failed ingest

A verification command that dies from a quoting error leaves the vault
untouched; the guarded operation already finished. Re-run the check, do not
re-run the ingest. The ingest script asserts raw and page hashes internally and
will refuse to report `complete` on a mismatch.
