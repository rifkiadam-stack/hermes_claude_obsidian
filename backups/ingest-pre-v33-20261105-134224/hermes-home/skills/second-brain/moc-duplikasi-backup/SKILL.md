---
name: moc-duplikasi-backup
description: Gunakan saat diminta review MOC, duplikasi, atau backup.
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [windows]
metadata:
  hermes:
    tags: [second-brain, moc, duplikasi, backup, maintenance]
    related_skills: [wiki, wiki-lint, wiki-fold]
---

# MOC, Duplikasi & Backup (Maintenance Bulanan Second Brain)

## When to Use

Gunakan ketika Adam meminta:
- "jalankan skill MOC, duplikasi dan backup" (kedua prosedur sekaligus)
- "review MOC" / "cek MOC" / "MOC freshness" (Prosedur A)
- "cek duplikasi" / "review duplikasi" (Prosedur A)
- "backup vault" / "checkpoint" (Prosedur B)

Skill untuk maintenance berkala vault Second Brain Adam. Ada DUA prosedur:
jalankan sesuai permintaan user (bisa salah satu, bisa keduanya sekaligus).
Trigger umum: "jalankan skill MOC, duplikasi dan backup", "review MOC",
"cek duplikasi", "backup vault", "checkpoint".

- **VAULT:** `G:\My Drive\hermes_obsidian`
- **CORE:** `C:\Users\rahmazaki.adam\AppData\Local\hermes\components\claude-obsidian-core`
- **Lint CLI:** `python "<CORE>/scripts/claude-obsidian.py" lint --vault "<VAULT>" --format json`

## Aturan mutasi (WAJIB)

- Semua perubahan vault lewat write guard `hermes_windows_write`:
  `inspect_operation` → ambil `approval_sha256` → `prepare_operation` → tulis file sesuai `writes` → `verify_operation`.
- DILARANG `write_file`/`patch` langsung ke vault.
- Review MOC/duplikasi = READ-ONLY (lapor saja, jangan ubah apa pun).
- Backup = hanya menyalin, TIDAK mengubah vault.

---

## Prosedur A — Review MOC & Duplikasi (bulanan, read-only)

Jalankan saat user minta "review MOC", "cek duplikasi", atau bagian review dari skill ini.

### A1. MOC Freshness
1. Daftar semua halaman di `wiki/mocs/`.
2. Untuk tiap MOC, baca isinya dan nilai:
   - Link masih relevan dengan topiknya?
   - Ada halaman baru di vault yang seharusnya masuk MOC tapi belum?
   - Topik dengan banyak halaman yang layak punya MOC baru?
   - MOC yang sudah tidak terpakai/usang?
3. Gunakan lint untuk data objektif: `stale_index_entries`, `dead_links`, `orphans` dari hasil lint.

### A2. Duplikasi
1. Cari halaman yang membahas topik serupa/overlap.
   Kandidat yang sudah diketahui: 3 halaman DNDF/NDF di `wiki/pekerjaan/derivatif-valas/`.
2. Untuk tiap kandidat: bandingkan isi, usulkan merge, cross-link, atau biarkan (dengan alasan).
3. Cross-check dengan lint `duplicate_basenames` dan `ambiguous_targets`.

### A3. Kontradiksi
1. Untuk topik yang sama di beberapa halaman, cek ada klaim bertentangan.
2. Catat sumber klaim (path halaman + baris) agar bisa diverifikasi user.

### Output
Kirim laporan (Bahasa Indonesia, terstruktur):
- Status tiap MOC + rekomendasi
- Daftar kandidat duplikasi + saran merge/cross-link
- Kontradiksi yang ditemukan
- **TIDAK mengeksekusi apa pun** — tunggu konfirmasi user sebelum mengubah vault.

---

## Prosedur B — Checkpoint Backup (bulanan, eksekusi penuh)

Jalankan saat user minta "backup", "checkpoint", atau bagian backup dari skill ini.

- **TUJUAN:** `C:\Users\rahmazaki.adam\Documents\hermes_obsidian_backup\`

### B1. Lint dulu
```bash
python "C:/Users/rahmazaki.adam/AppData/Local/hermes/components/claude-obsidian-core/scripts/claude-obsidian.py" lint --vault "G:/My Drive/hermes_obsidian" --format json
```
Laporkan hasil lint di laporan akhir (issue yang ada ikut dicatat).

### B2. Salin vault
1. Buat folder `C:\Users\rahmazaki.adam\Documents\hermes_obsidian_backup\hermes_obsidian_YYYY-MM-DD\` (tanggal hari ini).
2. Salin seluruh isi vault ke sana, KECUALI artefak runtime:
   - `.obsidian/workspace.json` & cache workspace
   - file lock (`*.lock`, `.vault-meta/hermes-windows/operations/*/write.lock`)
   - folder `.trash/` jika ada
3. Gunakan `robocopy` (Windows) atau `cp -r` via bash; pastikan struktur folder utuh.

### B3. Verifikasi
1. Hitung jumlah file `.md` di vault vs backup (harus sama).
2. Ambil sampel acak (min. 5 file): bandingkan SHA-256 sumber vs salinan.
3. Pastikan `assets/` dan `.raw/` ikut tersalin.

### B4. Rotasi
1. Hapus folder backup lebih tua dari 3 bulan.
2. JANGAN pernah hapus backup paling baru.
3. Lapor daftar backup yang dihapus.

### Output
Lapor: path backup lengkap, jumlah file, hasil verifikasi (jumlah .md + sampel hash), hasil lint, daftar backup lama yang dihapus.

---

## Pitfalls

- Guard TIDAK memvalidasi prefix path: path writes wajib diawali `wiki/` (mis. `wiki/mocs/...`), bukan `mocs/...`.
- `approval_sha256` adalah key yang benar dari `inspect_operation` (bukan `approved_plan_sha256`).
- Jangan pernah menghapus file di vault saat review; backup hanya menyalin.
- Vault tidak di-git otomatis — backup ini adalah satu-satunya safety net rutin.
