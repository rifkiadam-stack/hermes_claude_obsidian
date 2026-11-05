---
name: second-brain-native-windows
description: Gunakan saat operasi vault Second Brain native Windows.
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [windows]
metadata:
  hermes:
    tags: [obsidian, vault, windows, guard, bm25, css]
    related_skills: [wiki, wiki-ingest, wiki-retrieve, wiki-lint]
---

# Operasi Vault Second Brain di Native Windows

## When to Use

- Mutasi vault (restrukturisasi, ingest, fix lint, update index/MOC/ledger)
  - Untuk rename asset dan update embed, gunakan `references/asset-rename-workflow.md`.
- Provision/refresh BM25 index tanpa WSL
- Custom CSS Obsidian (folder colors, callouts)
- Troubleshooting: file "hilang", lint protes, guard menolak

Gunakan bersama skill `wiki`/`wiki-ingest`/`wiki-retrieve` (user-owned, baca
isi aslinya) — skill ini menampung pelajaran operasional Windows yang
dipelihara oleh curator.

## Aturan inti

- SEMUA mutasi vault wajib lewat guard `hermes_windows_write`. Setelah
  `inspect_operation` dan review `approval_sha256`, jalankan satu lifecycle
  tertutup melalui `execute_operation(vault, operation, approval_sha256)`, yang
  melakukan `prepare → apply → verify`. Satu bundle transaksi per operasi.
  DILARANG menulis `writes` secara manual atau memakai `write_file`/`patch`
  langsung ke vault.
- Jangan hapus file/pindahkan halaman tanpa persetujuan user.
- `contracts --verify` melaporkan `degraded` untuk wiki/wiki-cli/wiki-lint/
  wiki-retrieve di Windows — verifier butuh mutasi POSIX; artefak verifier,
  BUKAN kerusakan fungsional. Jangan jadikan alasan menolak operasi.

## Pitfalls write guard (teruji 2026-08-12)

0. **Gunakan helper native sejak awal**: pada Windows native, jangan mencoba `claude-obsidian.py transaction apply` untuk menulis vault; engine POSIX akan menolak dengan `UNSUPPORTED_PLATFORM`. Bangun operasi dalam schema `hermes-native-windows-reduced-v1`, panggil `hermes_windows_write.inspect_operation`, lalu gunakan `execute_operation` untuk lifecycle tertutup `prepare → apply → verify`.

0a. **Manifest request-owned**: jangan memasukkan `.raw/.manifest.json` sebagai direct write pada bundle ingest. Sumber manifest harus dinyatakan melalui `source_manifest_updates` pada engine POSIX atau dihasilkan oleh helper native sesuai operasi yang sudah diinspeksi. Direct write memicu `MANAGED_METADATA_COLLISION`.

1. **Key approval**: hasil `inspect_operation` memakai key
   `approval_sha256` (bukan `approved_plan_sha256`).
2. **Format expected hash**: `"sha256:<64-hex>"` untuk file yang ada;
   `null` untuk file baru.
3. **Path writes RELATIVE ke vault root, HARUS dengan prefix `wiki/`**:
   `"wiki/pekerjaan/derivatif-valas/x.md"`, bukan `"pekerjaan/..."`.
   Lupa prefix = file tertulis di root vault TANPA error guard; gejala:
   `pages_scanned` lint tidak bertambah + `stale_index_entries` melonjak.
4. **Jangan tambahkan H1 baru saat rewrite body yang sudah punya H1** —
   hasilnya H1 ganda → lint `empty_sections` melonjak (section pertama
   kosong). Buang semua H1 dari body lama, baru tulis satu H1.
5. **Source ledger**: key harus ID stabil `stable_source_id(kind, locator,
   sha)` (bukan slug bebas); record butuh `origin` (dict kind+locator),
   `content_kind`, `authority`, `review_status`, `title`, `content_sha256`,
   `ingested_at`, dan `pages` (array path halaman). Format salah = 1
   `provenance_error` per record.
6. **log.md**: entri baru prepend SETELAH frontmatter; menaruh entri di atas
   frontmatter membuat frontmatter invalid → `missing_frontmatter`.
7. **Ingest wajib arsip `.raw/` di transaksi yang sama**: salinan create-only
   ke `.raw/` + ledger locator `.raw/...` + manifest, BARU kemudian halaman
   `wiki/`. Ingest yang hanya menulis halaman membuat sumber yatim di inbox
   (pitfall batch 27, 2026-08-12). Remediasi: transaksi `archive-...`;
   `stable_source_id` berubah saat locator berubah (`inbox/` → `.raw/`) —
   ledger harus dihitung ulang, bukan sekadar ganti string locator.
8. **Cleanup staging aktif setelah review PASS (2026-08-13)**: pada setiap
   ingest—baik request langsung/interaktif maupun cron—setelah ingest dan
   provenance terverifikasi, jalankan fase kedua melalui
   `second_brain_staging_cleanup.py --apply-verified`. Delete primitive resmi
   memakai authority/approval hash, read preconditions untuk `.raw`, ledger,
   manifest, dan halaman, serta checkpoint before-image. Target dibatasi direct
   child `inbox/`/`Clippings/`; `.gitkeep` dan `.raw/` selalu dipertahankan.
   File blocked tidak boleh dibersihkan.
9. **Halaman hasil ingest wajib frontmatter lengkap**: selain `type`, `title`,
   dan `status`, sertakan `created` dan `updated`; lint dapat menandai halaman
   sebagai `missing_frontmatter` walaupun delimiter frontmatter sudah ada.
10. **Lifecycle guard wajib tertutup**: setelah review hasil
    `inspect_operation`, panggil `execute_operation(vault, operation,
    approval_sha256)`. Helper ini menjalankan `prepare → apply → verify` dan
    hanya mengembalikan sukses setelah operation `complete` serta `write.lock`
    dirilis. Jangan lagi menulis bundle secara manual atau berhenti pada status
    `applied`. Jika apply gagal, checkpoint dan lock sengaja dipertahankan agar
    partial state tidak tersembunyi.
11. **Recovery prepared operation bersifat fail-closed**: gunakan
    `recover_prepared_operation(vault, operation, approval_sha256)` hanya dengan
    authority operation asli. Recovery menolak PID pemilik yang masih hidup,
    host berbeda, target parsial, atau drift. Hanya operation dengan owner lokal
    yang sudah mati dan seluruh target persis cocok `after_sha256` yang boleh
    difinalisasi menjadi `complete` dan merilis lock. Jangan memanggil
    `inspect_operation` ulang setelah target create-only sudah terbentuk dan
    jangan menghapus/meretire lock secara paksa.
12. **Lint `empty_sections`/`dead_links` (teruji 2026-09-03)**: 13 `empty_sections` ternyata heading rata — heading induk (`### A. What is AI?`) dan subheading (`### 1. Machine Learning`) sama-sama `###`, sehingga induk dianggap kosong. Naikkan heading induk huruf ke `##` (jangan hapus konten). Dua `dead_links` `[[@handle]]` adalah atribusi penulis (username X/Twitter) yang salah format sebagai wikilink — ubah jadi tautan eksternal `[@handle](https://x.com/handle)` atau plain text di metadata, jangan buat halaman kosong. Terapkan dalam satu guarded operation, lalu lint ulang + `bm25_provision_native.py`; terverifikasi 15 → 0 findings tanpa regresi.

## Native Windows pasted-MU ingest fallback

Jika `claude-obsidian.py transaction apply` menolak dengan `UNSUPPORTED_PLATFORM` pada Windows native, jangan menulis vault secara langsung dan jangan memaksa CLI POSIX. Ubah bundle yang sudah direview menjadi operasi `hermes-native-windows-reduced-v1`: semua `content_file` harus dibaca menjadi `content` inline, setiap target yang sudah ada memakai expected hash berformat `sha256:<64 hex>`, dan file baru memakai `null`. Jalankan `inspect_operation(vault, operation)`, review `approval_sha256`, lalu satu lifecycle `execute_operation(vault, operation, approval_sha256)` dari `claude_obsidian.hermes_windows_write`. Verifikasi wajib mencakup `state: complete`, hash raw/ledger/manifest, halaman/MOC/log/hot, serta `write.lock` sudah tidak ada. Untuk `.raw/.manifest.json`, gunakan mekanisme request-owned atau masukkan hasil manifest sebagai write inline hanya pada helper native; jangan mengirim direct manifest write ke POSIX CLI ingest.

## BM25 native Windows (tanpa WSL)

`bm25-index.py build` & `contextual-prefix.py` menolak native Windows
(MutationLock POSIX → `ERR UNSUPPORTED_PLATFORM`). Solusi teruji:
adapter `scripts/bm25_provision_native.py` (idempotent, exit 0=diperbarui /
2=no-op), yang juga merekonsiliasi stale/surplus chunk dan memulihkan gap
chunk-commit/index-write:

1. Load modul internal via `importlib.util.spec_from_file_location`
   (nama file `contextual-prefix.py` ada dash → tak bisa import biasa).
2. Pakai fungsi read-only: `collect_pages`, `chunk_body`,
   `generate_prefix(tier-3 synthetic, tanpa LLM/egress)`. Bangun index dari
   snapshot record in-memory via `build_index_from_records()` — HANYA panggil
   `bm.tokenize()`; JANGAN panggil `bm.build_index()`/`discover_chunks()` yang
   membaca chunk/source via `Path.read_text`/`read_bytes` tanpa batas. Baca
   setiap file (page/chunk/index) lewat `bounded_target_bytes` /
   `bounded_target_hash` dari guard, bukan direct `read_text`/`read_bytes`.
   Address collision diperiksa inline (hard-fail `RuntimeError`), bukan lewat
   `preflight_unique_addresses()` yang return-value-nya mudah terabaikan.
3. Bentuk **desired chunk set** dari seluruh halaman. Rekonsiliasi chunk dalam
   satu operasi guard: tulis chunk berubah dan hapus hanya surplus dengan pola
   tepat `.vault-meta/chunks/<address>/chunk-NNN.json`. Jangan pernah memakai
   `unlink`/`rm` langsung atau membuka delete untuk metadata `.vault-meta` lain.
   Skip hanya jika seluruh field deterministik expected cocok; abaikan hanya
   `created_at`, agar rename stable-address tetap memperbarui `page_path`.
4. Setelah mutasi chunk, selalu build candidate index dari snapshot record yang
   sama (bukan re-read disk) dan bandingkan semantic content dengan index
   existing (abaikan hanya `updated_at`). Tulis index lewat guard bila berbeda.
   Jangan mendasarkan rebuild hanya pada jumlah mutasi run saat ini: retry
   sesudah chunk commit/index failure harus pulih.
   5. Untuk indeks yang melewati payload transaksi umum 8 MiB, adapter native memakai `claude_obsidian.hermes_windows_bm25` **hanya** untuk `.vault-meta/bm25/index.json`: approval mengikat hash byte indeks, hash lama, dan hash sumber/chunk; writer memakai lock Hermes bersama, batas berkas 64 MiB, stage satu berkas, dan atomic replace. Jangan menaikkan `MAX_TRANSACTION_RUNTIME_JSON_BYTES` atau mengalihkan konten wiki/ledger/manifest ke jalur indeks. Crash sesudah replace menyisakan lock untuk recovery dead-owner yang memeriksa hash before/after; ini tetap reduced-guarantee native Windows, bukan transaksi multi-berkas POSIX. Verifikasi dengan adapter produksi, `bm25-index.py stats`, retrieval `--no-rerank --explain` (stale 0), rerun exit 2, dan lock tidak ada.

   Pitfalls hardening (teruji 2026-08-27):
- **Index JSON wajib compact** `json.dumps(index, separators=(",", ":"))` — mengurangi ukuran cache dan I/O. Untuk vault lama ketika adapter masih menulis indeks via transaksi umum, pretty JSON melebihi `MAX_TRANSACTION_RUNTIME_JSON_BYTES` (8 MiB); indeks besar sekarang memakai jalur indeks khusus, bukan memperbesar batas transaksi umum.
- **Chunk apply dan index apply adalah dua lifecycle terpisah.** Jika adapter
  sudah melaporkan `chunk mutations applied` lalu index guard menolak payload
  karena batas JSON, chunk set mungkin sudah maju sementara BM25 index tetap
  lama. Jangan menganggap provisioning sukses dari pesan chunk saja: baca
  `bm25-index.py stats` dan bandingkan `doc_count`/`updated_at`; laporkan status
  parsial secara eksplisit bila index belum mencakup halaman terbaru. Jangan
  mengulang ingest konten—transaksi ingest yang sudah `complete` tetap selesai,
  terpisah dari status indeks. Catat error dan statistik aktual; jangan klaim
  ada solusi provisioning sebelum index write terverifikasi.
- **Bind index write ke snapshot**: masukkan `source_hashes` (page) + hash tiap
  desired chunk sebagai `read_preconditions` pada operasi index, agar source
  tidak berubah antara generate dan index-write. Operasi chunk juga memakai
  `read_preconditions = source_hashes`.
- **operation ID** pakai `uuid4().hex[:12]` — timestamp detik bisa collision,
  dan UUID penuh (32 hex) membuat checkpoint path melebihi batas Windows
  (`WinError 206`).
- **page_path record** pertahankan format native Windows (`str(Path)` →
  backslash) agar tidak memicu rewrite massal; path POSIX (`as_posix`) hanya
  untuk `bounded_target_*` dan rel index.
- **Self-recovery stale lock**: `apply_guard` menangkap `CooperativeLockError`
  lalu memulihkan `write.lock` yang tertinggal owner mati — baca `owner.json`
  (validasi `operation_id` portabel + `approval_sha256`), lalu
  `recover_prepared_operation` (fully-applied-dead-owner) atau
  `rollback_operation` (partial/drift), kemudian retry operasi baru. Fail-closed:
  owner masih hidup / lock tanpa owner / checkpoint invalid → `CooperativeLockError`
  dengan pesan jelas dan exit 1, bukan traceback. Tanpa ini, crash sekali saat
  `execute_operation` membuat semua run berikutnya wedge di `lock.mkdir()`.

Regression minimum sebelum produksi:
- halaman fixture dihapus → chunk lamanya hilang melalui guard dan
  `docs[*].path` index tidak memuat path chunk lama;
- rename dengan explicit address + isi sama memperbarui chunk `page_path`;
- duplicate explicit address gagal sebelum operasi guard;
- simulasi chunk sudah baru/index lama dipulihkan pada run berikutnya;
- path metadata sekitar scope tetap ditolak;
- run no-change menghasilkan exit `2` dan `write.lock` tidak tersisa.

Detail lengkap + schema chunk + verifikasi: lihat
`references/bm25-native-windows.md` (di skill ini) dan docs
`second-brain-operations.md` (status BM25 AKTIF) dan script adapter.
Verifikasi produksi: catat baseline `updated_at`, jumlah chunk, stale chunk, dan
`stale_candidates_skipped`; jalankan adapter; lalu `bm25-index.py stats` dan
`retrieve.py --no-rerank --explain`. Target postcondition: index terbaru,
retrieval `strategy: bm25-only`, stale chunk 0, `stale_candidates_skipped: 0`,
run ulang exit `2`, serta `write.lock` tidak ada. Cron harian harus menyebut
command dan path adapter eksplisit sebelum query test agar agent tidak mencari
adapter di lokasi core yang keliru.

## CSS folder colors (Obsidian)

- Warna nama folder: `.nav-folder-title[data-path^="wiki/<domain>"] { color }`.
- **Ikon folder TIDAK ikut berubah hanya dengan `color`** — butuh
  `--icon-color` pada title + selector langsung ke svg:
  `.nav-folder-title[data-path^="..."] .nav-folder-title-content svg { color }`.
- Gradasi per level (induk gelap → turunan muda):
  `color-mix(in srgb, var(--c-x) 60%, white 40%)` — didukung Chromium Obsidian.
- Snippet di `.obsidian/snippets/vault-colors.css`; user harus refresh di
  Settings → Appearance → CSS snippets setelah file diganti.
- Snippet lama (struktur baseline) perlu ditimpa saat struktur vault berubah.

## Graph View colors — BUKAN CSS (tervalidasi 2026-08-12)

Kalau user mengeluh "dot/ikon folder tetap satu warna" padahal nama folder sudah
berwarna, kemungkinan besar yang dimaksud adalah **node di Graph View**, bukan
File Explorer. Graph View TIDAK membaca CSS snippet sama sekali.

- Konfigurasi warna Graph View ada di `.obsidian/graph.json` → `colorGroups`:
  array `{"query": "path:wiki/<domain>", "color": {"a": 1, "rgb": 0x3b82f6}}`.
  `colorGroups` yang kosong (`[]`) = semua node satu warna default.
- Urutan grup penting: **anak folder dulu** (warna muda via `color-mix`),
  induk terakhir (warna penuh) — anak menang karena query lebih spesifik.
- Setelah edit `graph.json`, refresh snippet/toggle CSS TIDAK berpengaruh.
  User harus **menutup dan membuka ulang tab Graph View** (atau restart
  Obsidian) agar `colorGroups` terbaca. Jangan klaim selesai tanpa verifikasi
  visual user.
- Mutasi `graph.json` tetap wajib lewat write guard (bagian vault).

## Native Windows binary asset limitation

`hermes_windows_write` accepts UTF-8 string content only; do not bypass the guard with generic file writes, terminal copy, or Python writes inside the vault. When a requested canonical note needs an image already in `inbox/`:

1. Keep the original binary in place and use a vault-relative Obsidian embed such as `![[inbox/image.jpg]]` so the note renders.
2. For a durable reversible archive through the native guard, store base64 text create-only under `.raw/captured/<filename>.<ext>.base64.txt`. The source-ledger `content_sha256`, stable source ID, and raw-manifest `sha256` must match the stored base64-text bytes; verify that decoding those bytes reproduces the original inbox image hash.
3. The base64 archive is not byte-identical to the image. The staging cleanup verifier may correctly mark the original image `blocked`; retain it while the canonical embed depends on it. Do not delete it or claim that the raw binary was archived.
4. Report that the embed depends on the retained inbox asset and that a guard-supported binary asset workflow is needed before moving/cleaning it.

## Native Windows pasted-source and Clippings ingest

For a user-requested pasted source or a file under `Clippings/` when WSL is unavailable, do not bypass the POSIX transaction guard or write vault files directly. Use the native `claude_obsidian.hermes_windows_write` reduced-guarantee lifecycle: build one operation with exact `expected_hashes`, call `inspect_operation`, then `execute_operation` with the returned approval hash; verify the operation reaches `complete` and `write.lock` is released.

For a Clippings batch, preserve the source bytes as a create-only `.raw/` payload, create a canonical page under the relevant wiki domain, and update the source ledger, `.raw/.manifest.json`, active MOC/index, `wiki/log.md`, and `wiki/hot.md` in the same guarded operation. Preserve external image/video URLs; do not download remote assets unless explicitly requested. After read-back verifies raw bytes, ledger/manifest SHA-256, canonical page, and lint has no new findings, run a separate guarded cleanup operation limited to the ingested direct child of `Clippings/` or `inbox/`. Keep the `.raw/` archive.

Important newline pitfall: native Windows writes may normalize line endings. Always hash the actual post-apply `.raw/` bytes and reconcile ledger/manifest to that read-back hash in a second guarded operation if necessary; never assume the staging hash is the durable raw hash.

## Interactive and scheduled staging cleanup

Cleanup is part of every completed ingest lifecycle, not only the 19:00 WIB
cron. After a direct user-request ingest, run lint and the cleanup runner's
`--discover`; apply `--apply-verified` only when the source has a complete
ledger/manifest/raw/page proof and `blocked` is empty. A chat-pasted source
outside `inbox`/`Clippings` has no staging file and therefore produces a
cleanup no-op.

For lint, capture a baseline before the ingest when practical. Distinguish
new operation regressions from pre-existing findings; do not broaden a small
ingest into an unrelated repair unless explicitly requested.

The cleanup guard's durable proof pattern is documented in
`references/staging-cleanup-guard.md`.

## Arsip sumber dari inbox/ ke .raw/ (tervalidasi 2026-08-12)

Konvensi aktif: `inbox/` dan `Clippings/` = staging user-owned yang dibersihkan
otomatis hanya setelah ingest terverifikasi penuh; `.raw/` = arsip immutable
create-only yang tidak pernah dihapus otomatis. Arsip dan halaman dibuat dalam
transaksi ingest; cleanup staging dilakukan sebagai fase kedua melalui adapter
recoverable. Cron maintenance melaporkan file blocked yang belum memenuhi
provenance chain, bukan menghapusnya.

Recipe arsip satu bundle guard (`hermes-native-windows-reduced-v1`):
1. 27 writes salinan konten `inbox/<name>.md` → `.raw/<name>.md` (create-only).
2. Rewrite `wiki/meta/ledgers/source-ledger.json` — ganti locator
   `inbox/...` → `.raw/...` di semua record.
3. Update `.raw/.manifest.json` → `sources` keyed by source id, nilai
   `{path, sha256, archived_at}`.
4. Entri baru di `wiki/log.md` (prepend setelah frontmatter).
5. Verifikasi: lint 0 `provenance_error`, hash `.raw/` vs `inbox/` identik.

**PITFALL `stable_source_id`:** ID dihitung dari `(kind, locator, sha256)` —
mengubah locator `inbox/` → `.raw/` MENGUBAH SEMUA source ID di ledger. Rewrite
seluruh dict `sources` dengan ID baru (`stable_source_id('file',
'.raw/<name>.md', sha_hex)`), jangan hanya update locator pada record lama.
File `inbox/`/`Clippings/` baru dibiarkan utuh sampai verifikasi ingest lengkap;
setelah itu cleanup adapter memindahkannya ke checkpoint recovery.

## Cron maintenance vault

- `second-brain-daily-maintenance` (setiap hari 19:00 WIB): lint → fix aman →
  BM25 provision → fold hot/log (tanpa threshold; token tidak masalah) → cek
  inbox → query test 1 pertanyaan tetap ("Apa bedanya NDF dan DNDF?").
- Lapor: "vault sehat ✅" + detail; alarm hanya saat query test 0 hasil.
- Cron schedule 5-field (`30 17 * * *`); hati-hati 6-field (`0 17 30 * * *`)
  di-parse sebagai tanggal lain.
