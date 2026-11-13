# BM25 Provisioning — Native Windows (detail teknis, teruji 2026-08-28)

## Upstream failure mode

`bm25-index.py build` and `contextual-prefix.py` wrap writes in
`MutationLock(VAULT_ROOT, timeout=0.0)` → POSIX directory-descriptor
confinement required → native Windows fails closed:

```
ERR UNSUPPORTED_PLATFORM: vault writes require directory-descriptor
confinement (WSL/Linux or supported macOS); on native Windows run this
command inside WSL — read-only inspection and dry-runs work natively
```

Read-only modes (stats, query, --peek) work natively. WSL is NOT the only
option — do not present it as mandatory.

## Working adapter

`<PRODUCT_ROOT>/scripts\bm25_provision_native.py`

Pipeline: scan wiki pages → hard-fail bila address preflight mengembalikan
`False` → generate desired chunk records (tier-3 synthetic prefix, no LLM, no
egress) → hitung surplus terhadap existing chunk set → satu operasi guard untuk
write berubah + delete surplus → build candidate index dari disk → bandingkan
semantic index (abaikan hanya `updated_at`) → guarded write index bila berbeda.
Setiap mutasi vault melalui `hermes_windows_write`; semantic compare membuat
retry pulih bila chunk commit berhasil tetapi index write sebelumnya gagal.

Delete scope harus fail-closed: hanya direct-child staging yang memang didukung
guard atau cache turunan dengan pola tepat
`.vault-meta/chunks/<address>/chunk-NNN.json`. Path metadata lain, nama chunk
malformed, dan nested path tambahan wajib ditolak. Quarantine/checkpoint harus
mereplikasi parent chain secara guarded agar delete tetap rollback-capable.

### Load dash-named scripts as modules

```python
import importlib.util
def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

cp = load_module("contextual_prefix", SCRIPTS / "contextual-prefix.py")
bm = load_module("bm25_index", SCRIPTS / "bm25-index.py")
```

### Read-only functions reused (no MutationLock)

- `cp.configure_vault(str(vault))` — set globals VAULT_ROOT/CHUNKS_DIR
- `cp.collect_pages(None)` — all wiki pages
- `cp.preflight_unique_addresses(pages)` — collision check before writing
- `cp.read_page(path)`, `cp.parse_frontmatter(body)`, `cp.chunk_body(content)`
- `cp.derive_synthetic_address(page_path)` — address fallback
- `cp.pick_prefix_tier(force_synthetic=True, allow_egress=False)` → tier-3
- `cp.generate_prefix(tier, fm, body, chunk_text)` → (prefix, prefix_source)
- `bm.configure_vault(str(vault))`, `bm.build_index()` — reads chunks from disk

### Chunk record schema

`.vault-meta/chunks/<address>/chunk-<idx>.json`:

```json
{"schema_version": 1, "page_path": "wiki/...", "page_address": "...",
 "chunk_index": 0, "raw_text": "...",
 "contextualized_text": "<prefix>\n\n<raw>",
 "prefix": "", "prefix_source": "synthetic", "char_count": N,
 "body_hash": "<sha256 of raw>", "page_body_hash": "<sha256 of page>",
 "created_at": "ISO-UTC"}
```

Address format: `syn-<sha256-of-page-path>` when frontmatter has no address.

### Idempotency, stale reconciliation, dan crash recovery (daily-cron safe)

- `cp.preflight_unique_addresses(pages)` mengembalikan boolean; `False` wajib
  diperlakukan sebagai hard error sebelum mutation set dibuat. Jangan hanya
  menangkap `SystemExit`.
- Skip chunk write hanya bila **semua field deterministik record expected**
  cocok (`schema_version`, `page_path`, `page_address`, `chunk_index`, text,
  prefix, source, counts, dan hashes). Abaikan hanya `created_at`. Perbandingan
  parsial berbasis content hash tidak cukup: rename halaman dengan explicit
  address dan isi sama tetap harus memperbarui `page_path`.
- Build desired relative-path set saat scan seluruh halaman. Enumerate hanya
  regular, non-symlink `chunk-NNN.json` direct children; surplus = existing −
  desired. Surplus mencakup halaman terhapus dan excess chunk saat halaman
  menjadi lebih pendek.
- Submit changed writes dan surplus deletes dalam satu guarded chunk operation.
  Gunakan operation ID beresolusi mikrodetik/UUID agar retry cepat tidak
  bertabrakan dengan checkpoint operation sebelumnya.
- Setelah chunk operation, **selalu build candidate index secara read-only**.
  Bandingkan semantic content candidate dengan index existing sambil
  mengabaikan hanya `updated_at`; tulis index bila berbeda atau invalid/missing.
  Jangan memutuskan rebuild hanya dari jumlah mutasi chunk pada run saat ini.
  Jika chunk commit sukses lalu index write gagal, run berikutnya harus melihat
  semantic mismatch dan menyelesaikan index recovery.
- Exit `2` hanya bila tidak ada write/delete chunk **dan** candidate index
  semantically equal. Exit `0` untuk chunk mutation atau index recovery; exit
  `1` untuk error.

Regression fixture minimum:
1. Provision dua halaman, hapus satu, provision lagi; assert stale chunk absent
   dan `docs[*].path` pada index tidak memuat path chunk lama. Schema index tidak
   memiliki `docs[*].page_path`, jadi assertion pada field itu adalah false
   positive.
2. Provision ulang tanpa perubahan; assert exit `2` dan tidak ada `write.lock`.
3. Rename halaman dengan explicit address valid dan isi identik; assert chunk
   `page_path` berubah. Untuk fixture Windows, tulis frontmatter dengan LF
   eksplisit karena parser address mengharapkan LF.
4. Simulasikan state chunk sudah ter-commit tetapi index masih lama; run normal
   wajib menulis index baru dan menghilangkan vocabulary lama.
5. Dua halaman dengan explicit address sama wajib gagal di preflight sebelum
   operasi guard dibuat.
6. Guard negative tests wajib menolak `.vault-meta/bm25/index.json`, malformed
   chunk names, shortened parent chains, dan deeper nested paths; positive test
   wajib membuktikan delete chunk, checkpoint/quarantine, verify, rollback, dan
   lock release tetap bekerja.

### Verification

Capture a read-only baseline first: index `updated_at`, chunk count, stale chunk
paths, `write.lock`, and one fixed retrieval's `stale_candidates_skipped`.

```bash
unset PYTHONPATH && python "<PRODUCT_ROOT>/scripts/bm25_provision_native.py" \
  --vault "<VAULT>"

python scripts/bm25-index.py --vault <vault> stats
# expect doc_count/vocab_size/avg_dl, NOT "no index"

python scripts/retrieve.py --vault <vault> "Apa bedanya NDF dan DNDF?" \
  --top 5 --no-rerank --explain
# expect strategy=bm25-only, sensible hits, stale_candidates_skipped=0
```

Then rerun the adapter: expect exit `2`/`UNCHANGED`. Confirm stale chunk count is
0 and `.vault-meta/hermes-windows/write.lock` is absent. Distinguish focused
changed-path tests from repository-wide native-Windows failures; never report a
full suite as passing when POSIX/symlink/release baseline tests remain blocked.

### contracts --verify status

`contracts --verify --capability wiki-retrieve` reports `degraded` on Windows
("verification failed with exit code 1"). The verifier needs a POSIX mutation
to run its behavioral test; that is a verifier artifact, NOT functional
breakage — retrieve.py provably works with the built index. Re-check after
core updates; no action needed otherwise.

## Cron integration

`second-brain-daily-maintenance` (daily 19:00 WIB) runs the adapter before
the query test: index stays fresh after ingest; no-op when nothing changed.
