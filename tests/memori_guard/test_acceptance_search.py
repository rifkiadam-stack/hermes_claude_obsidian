"""Uji penerimaan kotak hitam Fase E: tool `cari` dan perluasan `baca` (amandemen 3).

Acuan, dari yang paling berlaku: `amandemen-kontrak-4-cari.md`, lalu
`amandemen-kontrak-3-cari.md` bagian 1, 2, dan 4. Kontrak dan amandemen 1–2
tetap berlaku; T0–T17 di `test_memori_guard.py` tidak diubah dan menjadi regresi.
Tafsiran yang masih terbuka ditandai `TAFSIRAN:` dan dirangkum di
`LAPORAN-TES-SIAP-FASE-E.md`.

Tes ini tidak mengimpor kode Hermes dan tidak membuat indeks sendiri. Indeks BM25
dibangun dengan perintah Hermes dari `MEMORI_GUARD_BUILD_INDEX_CMD`; tes yang
membutuhkannya di-skip jika variabel itu kosong.
"""

from __future__ import annotations

import json
import math
import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from conftest import potret, potret_penuh, sha_file
from mcp_klien import KODE_BANGUN_BERHASIL, jalankan_bangun_indeks

# Amandemen 4 §2: ISO 8601 UTC dengan akhiran `Z`.
# TAFSIRAN: detik pecahan (`.123`) boleh ada atau tidak.
POLA_DIBANGUN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")

BATAS_KUERI = 500
BATAS_CUPLIKAN = 500
JUMLAH_BAWAAN = 5
JUMLAH_MAKS = 10
KUNCI_ITEM = {"path", "judul", "type", "skor", "cuplikan"}

# Halaman di fixtures/pengetahuan-vault. "obligasi" ada di tepat tujuh halaman ini.
HALAMAN_OBLIGASI = [
    "wiki/konsep/obligasi-negara.md",
    "wiki/konsep/kupon-tetap.md",
    "wiki/konsep/panjang-sekali.md",
    "wiki/sumber/laporan-lelang-2026.md",
    "wiki/sumber/arsip/2025/catatan-pasar.md",
    "wiki/entitas/penerbit-fiktif.md",
    "wiki/sesi/uji-cari.md",
]
HALAMAN_UNIK = "wiki/konsep/kupon-tetap.md"        # satu-satunya yang memuat "zirkonium"
CATATAN_SESI = "wiki/sesi/uji-cari.md"             # satu-satunya yang memuat "kalsedon"
HALAMAN_PANJANG = "wiki/konsep/panjang-sekali.md"  # isi > 3000 karakter
HALAMAN_DALAM = "wiki/sumber/arsip/2025/catatan-pasar.md"
INDEKS_WIKI = "wiki/index.md"
# Amandemen 4 §2: judul = `title`, jika tidak ada H1 pertama, jika tidak ada nama file tanpa `.md`.
HALAMAN_JUDUL = {  # path: (kata unik, judul yang diharapkan)
    "wiki/konsep/judul-dari-h1.md": ("malakit", "Judul Dari H1"),
    "wiki/konsep/judul-frontmatter-menang.md": ("ametis", "Judul Frontmatter Menang"),
    "wiki/konsep/judul-dari-nama-file.md": ("peridot", "judul-dari-nama-file"),
}


# -- pembantu ------------------------------------------------------------------

def cek(hasil: Any, status: str, konteks: str = "") -> dict[str, Any]:
    assert isinstance(hasil, dict), f"{konteks}: hasil bukan objek JSON: {hasil!r}"
    assert hasil.get("status") == status, f"{konteks}: status {hasil.get('status')!r}, diharapkan {status!r}; hasil={hasil!r}"
    return hasil


def cek_pesan(hasil: dict[str, Any], status: str, konteks: str) -> str:
    cek(hasil, status, konteks)
    pesan = hasil.get("pesan")
    assert isinstance(pesan, str) and pesan.strip(), f"{konteks}: `pesan` kosong: {hasil!r}"
    return pesan


def cek_tanpa_hasil(hasil: Any, status: str, konteks: str) -> str:
    """Amandemen 5 A.11: `ditolak` dan `gagal` dari `cari` hanya `{status, pesan}`, tanpa field `hasil`."""
    cek(hasil, status, konteks)
    assert set(hasil) == {"status", "pesan"}, f"{konteks}: field {sorted(hasil)}, diharapkan hanya status dan pesan: {hasil!r}"
    pesan = hasil["pesan"]
    assert isinstance(pesan, str) and pesan.strip(), f"{konteks}: `pesan` kosong: {hasil!r}"
    return pesan


def cari(klien, kueri: str, jumlah: int | None = None) -> Any:
    argumen: dict[str, Any] = {"kueri": kueri}
    if jumlah is not None:
        argumen["jumlah"] = jumlah
    return klien.panggil("cari", **argumen)


_ELIPSIS = re.compile(r"^(?:…|\.\.\.)+\s*|\s*(?:…|\.\.\.)+$")


def norm_spasi(teks: str) -> str:
    return re.sub(r"\s+", " ", teks).strip()


def cuplikan_literal(cuplikan: str, isi_halaman: str) -> bool:
    """Amandemen 5 B.19: setelah spasi dinormalkan dan elipsis di awal/akhir dibuang, `cuplikan`
    adalah substring dari isi halaman yang spasinya juga dinormalkan."""
    c = norm_spasi(cuplikan)
    c = norm_spasi(_ELIPSIS.sub("", c))
    return bool(c) and c in norm_spasi(isi_halaman)


def frontmatter(vault: Path, rel: str) -> dict[str, str]:
    """Frontmatter YAML sederhana (`kunci: nilai` satu baris), cukup untuk fixture uji."""
    baris = (vault / rel).read_bytes().decode("utf-8").splitlines()
    if not baris or baris[0].strip() != "---":
        return {}
    hasil: dict[str, str] = {}
    for b in baris[1:]:
        if b.strip() == "---":
            break
        if ":" in b and not b.startswith((" ", "\t")):
            k, v = b.split(":", 1)
            hasil[k.strip()] = v.strip().strip("'\"")
    return hasil


def judul_diharapkan(vault: Path, rel: str) -> str:
    """Amandemen 4 §2: `title` frontmatter; jika tidak ada H1 pertama; jika tidak ada nama file tanpa `.md`."""
    title = frontmatter(vault, rel).get("title", "")
    if title:
        return title
    teks = (vault / rel).read_bytes().decode("utf-8").splitlines()
    mulai = 0
    if teks and teks[0].strip() == "---":  # lewati frontmatter
        for i, b in enumerate(teks[1:], start=1):
            if b.strip() == "---":
                mulai = i + 1
                break
    for b in teks[mulai:]:
        if b.startswith("# ") and b[2:].strip():
            return b[2:].strip()
    return Path(rel).name[: -len(".md")]


def cek_dibangun(nilai: Any, konteks: str) -> datetime:
    """Amandemen 4 §2: ISO 8601 UTC dengan akhiran `Z`."""
    assert isinstance(nilai, str) and POLA_DIBANGUN.match(nilai), f"{konteks}: indeks.dibangun {nilai!r} bukan ISO 8601 UTC berakhiran Z"
    try:
        return datetime.fromisoformat(nilai[:-1]).replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise AssertionError(f"{konteks}: indeks.dibangun {nilai!r} bukan tanggal sah: {exc}") from exc


def cek_hasil_cari(vault: Path, hasil: Any, konteks: str, jumlah: int = JUMLAH_BAWAAN,
                   ringan: bool = False) -> list[dict[str, Any]]:
    """`ringan=True` (hanya T23) melewati pemeriksaan yang membandingkan hasil dengan isi vault saat ini
    (berkas ada, judul, type, cuplikan literal), karena vault berubah di tengah panggilan."""
    cek_cuplikan = not ringan
    """Bentuk hasil `selesai` sesuai amandemen 3 §1 dan amandemen 4 §2. Mengembalikan daftar item."""
    cek(hasil, "selesai", konteks)
    indeks = hasil.get("indeks")
    assert isinstance(indeks, dict), f"{konteks}: `indeks` bukan objek: {hasil!r}"
    cek_dibangun(indeks.get("dibangun"), konteks)
    assert isinstance(indeks.get("basi"), bool), f"{konteks}: indeks.basi bukan boolean: {indeks!r}"
    items = hasil.get("hasil")
    assert isinstance(items, list), f"{konteks}: `hasil` bukan array: {hasil!r}"
    assert len(items) <= jumlah, f"{konteks}: {len(items)} hasil, melebihi jumlah {jumlah}"
    for item in items:
        assert isinstance(item, dict) and KUNCI_ITEM <= set(item), f"{konteks}: field kurang: {item!r}"
        rel = item["path"]
        # Amandemen 4 §2 dan amandemen 5 B.3: hanya `wiki/**`, .md, tanpa komponen bertitik.
        assert isinstance(rel, str) and rel.startswith("wiki/") and rel.endswith(".md"), f"{konteks}: path {rel!r}"
        komponen = rel.split("/")
        assert "\\" not in rel and ".." not in komponen and not Path(rel).is_absolute(), f"{konteks}: path {rel!r}"
        assert not any(k.startswith(".") for k in komponen), f"{konteks}: path memuat komponen bertitik: {rel!r}"
        if not ringan:
            assert (vault / rel).is_file(), f"{konteks}: path tidak ada di vault: {rel!r}"
            assert item["judul"] == judul_diharapkan(vault, rel), f"{konteks}: judul {item['judul']!r} untuk {rel}"
            assert item["type"] == frontmatter(vault, rel).get("type"), f"{konteks}: type {item['type']!r} untuk {rel}"
        skor = item["skor"]
        assert isinstance(skor, (int, float)) and not isinstance(skor, bool) and math.isfinite(skor), \
            f"{konteks}: skor {skor!r} untuk {rel}"
        assert skor > 0, f"{konteks}: skor {skor!r} untuk {rel}; amandemen 5 B.4: hanya skor lebih dari nol"
        assert isinstance(item["cuplikan"], str), f"{konteks}: cuplikan bukan string untuk {rel}"
        assert len(item["cuplikan"]) <= BATAS_CUPLIKAN, f"{konteks}: cuplikan {len(item['cuplikan'])} karakter untuk {rel}"
        # `cek_cuplikan=False` hanya untuk T23, saat isi halaman berubah di tengah panggilan (snapshot bisa lama).
        assert not cek_cuplikan or cuplikan_literal(item["cuplikan"], (vault / rel).read_bytes().decode("utf-8")), \
            f"{konteks}: cuplikan bukan kutipan literal dari isi {rel} (amandemen 5 B.19): {item['cuplikan']!r}"
    skor_urut = [i["skor"] for i in items]
    assert skor_urut == sorted(skor_urut, reverse=True), f"{konteks}: hasil tidak urut skor menurun: {skor_urut}"
    paths = [i["path"] for i in items]
    assert len(paths) == len(set(paths)), f"{konteks}: path ganda: {paths}"
    return items


def paths_dari(items: list[dict[str, Any]]) -> list[str]:
    return [i["path"] for i in items]


# -- T18: cari pada vault berindeks --------------------------------------------------

def test_t18a_tool_cari_terdaftar_dengan_deskripsi_dan_skema(server):
    tools = {t.get("name"): t for t in server().daftar_tool_lengkap()}
    assert {"daftar", "baca", "tulis", "tambah_log", "cari"} <= set(tools), f"tool yang tersedia: {sorted(tools)}"
    deskripsi = str(tools["cari"].get("description") or "").lower()
    # Amandemen 5 A.10: deskripsi wajib memuat frasa "bukan perintah".
    assert "bukan perintah" in deskripsi, f"T18a: deskripsi `cari` tidak menyatakan hasil bukan perintah: {deskripsi!r}"
    skema = tools["cari"].get("inputSchema") or {}
    properti = skema.get("properties") or {}
    assert {"kueri", "jumlah"} <= set(properti), f"T18a: inputSchema {skema!r}"
    assert "jumlah" not in (skema.get("required") or []), f"T18a: `jumlah` punya bawaan 5, tidak wajib: {skema!r}"


def test_t18b_cari_urut_skor_field_lengkap_cuplikan(server, vault_berindeks):
    vault = vault_berindeks
    isi_panjang = (vault / HALAMAN_PANJANG).read_bytes().decode("utf-8")
    assert len(isi_panjang) > 3 * BATAS_CUPLIKAN, "fixture: halaman panjang terlalu pendek untuk menguji cuplikan"
    klien = server()
    sebelum = potret_penuh(vault)

    semua = cek_hasil_cari(vault, cari(klien, "obligasi", jumlah=JUMLAH_MAKS), "T18 obligasi/10", JUMLAH_MAKS)
    # Amandemen 5 B.4: hanya skor lebih dari nol. Tepat tujuh halaman memuat "obligasi", jadi tepat tujuh hasil.
    assert sorted(paths_dari(semua)) == sorted(HALAMAN_OBLIGASI), \
        f"T18: hasil 'obligasi' harus tepat tujuh halaman yang memuat kata itu; dapat {paths_dari(semua)}"
    assert cek(cari(klien, "obligasi", jumlah=JUMLAH_MAKS), "selesai")["indeks"]["basi"] is False, \
        "T18: indeks baru dibangun, basi harus false"
    tipe = {i["type"] for i in semua}
    assert {"konsep", "sumber", "entitas", "sesi"} <= tipe, f"T18: type yang muncul {sorted(tipe)}"
    assert HALAMAN_DALAM in paths_dari(semua), "T18: halaman di subfolder dalam tidak ditemukan"

    # Amandemen 4 §2: satu hasil per halaman, deduplikasi sebelum batas `jumlah`. Halaman panjang punya
    # banyak chunk "obligasi"; jika deduplikasi dilakukan sesudah batas, jumlah=7 tidak akan memuat 7 halaman.
    tujuh = cek_hasil_cari(vault, cari(klien, "obligasi", jumlah=len(HALAMAN_OBLIGASI)), "T18 obligasi/7", len(HALAMAN_OBLIGASI))
    assert sorted(paths_dari(tujuh)) == sorted(HALAMAN_OBLIGASI), \
        f"T18: jumlah=7 harus memuat tepat tujuh halaman berbeda; dapat {paths_dari(tujuh)}"

    bawaan = cek_hasil_cari(vault, cari(klien, "obligasi"), "T18 obligasi/bawaan")
    assert len(bawaan) == JUMLAH_BAWAAN, f"T18: jumlah bawaan harus 5 (ada 7 halaman cocok), dapat {len(bawaan)}"
    tiga = cek_hasil_cari(vault, cari(klien, "obligasi", jumlah=3), "T18 obligasi/3", 3)
    assert len(tiga) == 3, f"T18: jumlah=3 dengan 7 halaman cocok, dapat {len(tiga)}"
    assert paths_dari(tiga) == paths_dari(semua)[:3], "T18: tiga teratas berbeda dari urutan hasil penuh"

    unik = cek_hasil_cari(vault, cari(klien, "zirkonium", jumlah=JUMLAH_MAKS), "T18 zirkonium", JUMLAH_MAKS)
    assert paths_dari(unik) == [HALAMAN_UNIK], f"T18: hanya satu halaman memuat 'zirkonium' (halaman skor nol tidak dikembalikan): {paths_dari(unik)}"
    sesi = cek_hasil_cari(vault, cari(klien, "kalsedon"), "T18 kalsedon")
    assert paths_dari(sesi) == [CATATAN_SESI] and sesi[0]["type"] == "sesi", f"T18: {sesi!r}"

    assert potret_penuh(vault) == sebelum, "T18: `cari` mengubah file di vault"


def test_t18c_indeks_basi_setelah_isi_atau_inventaris_berubah(server, vault_berindeks, bangun_indeks):
    # Amandemen 4 §3: hash indeks-chunk-halaman, waktu perubahan wiki/ vs updated_at, dan inventaris
    # halaman (tambah/hapus). Perubahan yang terdeteksi: basi true; setelah dibangun ulang: false.
    vault = vault_berindeks
    klien = server()

    def basi(nama: str) -> bool:
        return cek(cari(klien, "zirkonium"), "selesai", f"T18c {nama}")["indeks"]["basi"]

    assert basi("awal") is False, "T18c: indeks baru dibangun, basi harus false"

    time.sleep(2.1)  # mtime berikutnya pasti lebih baru dari waktu bangun indeks
    with open(vault / HALAMAN_UNIK, "ab") as f:
        f.write("Baris tambahan setelah indeks dibangun.\n".encode("utf-8"))
    assert basi("isi diubah") is True, "T18c: isi halaman diubah setelah indeks dibangun, basi harus true"
    bangun_indeks(vault)
    assert basi("setelah bangun ulang (ubah)") is False, "T18c: setelah bangun ulang basi harus false lagi"

    time.sleep(2.1)
    baru = vault / "wiki/konsep/uji-t18c-baru.md"
    baru.write_bytes("---\ntitle: Uji T18c Baru\ntype: konsep\n---\n\n# Uji T18c Baru\n\nHalaman baru.\n".encode("utf-8"))
    assert basi("halaman ditambah") is True, "T18c: halaman ditambah setelah indeks dibangun, basi harus true"
    bangun_indeks(vault)
    assert basi("setelah bangun ulang (tambah)") is False

    time.sleep(2.1)
    baru.unlink()
    assert basi("halaman dihapus") is True, "T18c: halaman dihapus setelah indeks dibangun, basi harus true"
    bangun_indeks(vault)
    assert basi("setelah bangun ulang (hapus)") is False


def test_t18d_judul_title_lalu_h1_lalu_nama_file(server, vault_berindeks):
    # Amandemen 4 §2. Tiap halaman fixture punya kata penanda unik supaya mudah dicari.
    vault = vault_berindeks
    klien = server()
    for rel, (kata, judul) in HALAMAN_JUDUL.items():
        assert judul_diharapkan(vault, rel) == judul, f"fixture {rel}: judul yang diharapkan {judul!r}"
        items = cek_hasil_cari(vault, cari(klien, kata), f"T18d {kata}")
        assert paths_dari(items) == [rel], f"T18d: hanya {rel} memuat {kata!r}: {paths_dari(items)}"
        assert items[0]["judul"] == judul, f"T18d: judul {items[0]['judul']!r} untuk {rel}, diharapkan {judul!r}"


def test_t18f_halaman_tanpa_type_memuat_type_null(server, vault_berindeks):
    # Amandemen 5 A.8: field `type` tetap ada dengan nilai null.
    vault = vault_berindeks
    rel = "wiki/konsep/tanpa-type.md"
    assert "type" not in frontmatter(vault, rel), "fixture: halaman ini tidak boleh punya type"
    items = cek_hasil_cari(vault, cari(server(), "kuarsa"), "T18f")
    assert paths_dari(items) == [rel], f"T18f: {paths_dari(items)}"
    assert "type" in items[0] and items[0]["type"] is None, f"T18f: type harus ada dengan nilai null: {items[0]!r}"


def test_t18h_halaman_di_hasil_bisa_langsung_dihapus_setelah_cari(server, vault_berindeks):
    # Fase F, kandidat kedua: server membaca halaman lalu menutup handle sebelum menjawab, sehingga halaman yang
    # muncul di hasil `cari` bisa langsung dihapus tanpa pengulangan (kandidat pertama menahan berkas, WinError 32).
    vault = vault_berindeks
    klien = server()
    dihapus: list[str] = []
    for kueri in ("zirkonium", "kalsedon", "malakit", "ametis", "peridot", "kuarsa", "obligasi"):
        items = cek_hasil_cari(vault, cari(klien, kueri, jumlah=JUMLAH_MAKS), f"T18h {kueri}", JUMLAH_MAKS)
        assert items, f"T18h: kueri {kueri!r} tidak menghasilkan halaman"
        for p in paths_dari(items):
            if not (vault / p).exists():
                continue  # sudah dihapus pada putaran sebelumnya (halaman yang sama muncul di dua kueri)
            try:
                (vault / p).unlink()  # langsung, tanpa pengulangan
            except PermissionError as exc:
                raise AssertionError(f"T18h: {p} tidak bisa dihapus langsung setelah `cari {kueri!r}` selesai: {exc}") from exc
            assert not (vault / p).exists(), f"T18h: {p} masih ada setelah dihapus"
            dihapus.append(p)
    assert len(dihapus) >= len(HALAMAN_OBLIGASI), f"T18h: hanya {len(dihapus)} halaman dihapus: {dihapus}"
    # Sesudahnya: halaman yang dihapus tidak muncul lagi (dibuang filter kesegaran) dan `cari` tidak galat.
    sisa = cek_hasil_cari(vault, cari(klien, "obligasi", jumlah=JUMLAH_MAKS), "T18h sesudah hapus", JUMLAH_MAKS)
    assert not (set(paths_dari(sisa)) & set(dihapus)), f"T18h: halaman terhapus masih muncul: {paths_dari(sisa)}"
    assert klien.proc.poll() is None, "T18h: server berhenti"


def test_t18g_hasil_hanya_wiki(server, vault_pengetahuan, bangun_indeks):
    # Amandemen 5 B.3: path hasil hanya `wiki/**`; hasil di luar `wiki/` dibuang.
    # Apakah penerbit indeks mengindeks file di luar `wiki/` tidak ditetapkan; tes memeriksa hasilnya saja.
    vault = vault_pengetahuan
    kata = "tanzanit"
    luar = ["sesi-log/uji-t18g-log.md", "_catatan-akar-t18g.md", "bukan-wiki/halaman.md"]
    for rel in luar:
        (vault / rel).parent.mkdir(parents=True, exist_ok=True)
        (vault / rel).write_bytes(f"---\ntitle: Luar\ntype: konsep\n---\n\n# Luar\n\n{kata} {kata} {kata}\n".encode("utf-8"))
    dalam = "wiki/konsep/uji-t18g-dalam.md"
    (vault / dalam).write_bytes(f"---\ntitle: Dalam\ntype: konsep\n---\n\n# Dalam\n\n{kata}\n".encode("utf-8"))
    bangun_indeks(vault)
    items = cek_hasil_cari(vault, cari(server(), kata, jumlah=1), "T18g", 1)
    assert paths_dari(items) == [dalam], f"T18g: jumlah=1 harus berisi halaman di wiki/ (hasil di luar wiki/ dibuang sebelum batas): {paths_dari(items)}"


def test_t18e_halaman_bertitik_tidak_dikembalikan(server, vault_pengetahuan, bangun_indeks):
    # Amandemen 4 §2 dan §5, amandemen 5 B.18: path hasil divalidasi dengan aturan baca, dan hasil yang
    # tidak lolos dibuang SEBELUM batas `jumlah`, sehingga posisinya diisi hasil sah berikutnya.
    # Apakah penerbit indeks mengindeks halaman bertitik tidak ditetapkan; tes memeriksa hasilnya saja.
    vault = vault_pengetahuan
    kata = "rodokrosit"
    bertitik = ["wiki/konsep/.draf.md", "wiki/.tersembunyi/rahasia.md", "wiki/sesi/.arsip/lama.md"]
    for rel in bertitik:  # skor lebih tinggi daripada halaman sah: kata diulang lebih sering
        (vault / rel).parent.mkdir(parents=True, exist_ok=True)
        (vault / rel).write_bytes(f"---\ntitle: Tersembunyi\ntype: konsep\n---\n\n# Tersembunyi\n\n{(kata + ' ') * 8}\n".encode("utf-8"))
    sah = "wiki/konsep/uji-t18e-sah.md"
    (vault / sah).write_bytes(f"---\ntitle: Uji T18e\ntype: konsep\n---\n\n# Uji T18e\n\n{kata}\n".encode("utf-8"))
    bangun_indeks(vault)
    klien = server()
    items = cek_hasil_cari(vault, cari(klien, kata, jumlah=JUMLAH_MAKS), "T18e", JUMLAH_MAKS)
    assert paths_dari(items) == [sah], f"T18e: hanya halaman sah yang boleh dikembalikan: {paths_dari(items)}"
    satu = cek_hasil_cari(vault, cari(klien, kata, jumlah=1), "T18e jumlah=1", 1)
    assert paths_dari(satu) == [sah], \
        f"T18e: jumlah=1 harus berisi halaman sah, bukan kosong karena hasil teratas dibuang sesudah batas: {paths_dari(satu)}"


# -- T19: baca halaman pengetahuan, tulis tetap ditolak -------------------------------

def test_t19_baca_halaman_pengetahuan_selesai_tulis_ditolak(server, vault_pengetahuan):
    vault = vault_pengetahuan
    klien = server()
    for rel in (HALAMAN_UNIK, HALAMAN_DALAM, INDEKS_WIKI, HALAMAN_PANJANG):
        hasil = cek(klien.panggil("baca", path=rel), "selesai", f"T19 baca {rel}")
        assert hasil.get("path") == rel and hasil.get("ada") is True, f"T19 baca {rel}: {hasil!r}"
        assert hasil.get("isi") == (vault / rel).read_bytes().decode("utf-8"), f"T19 baca {rel}: isi tidak sama byte per byte"
        assert hasil.get("sha256") == sha_file(vault, rel), f"T19 baca {rel}: hash {hasil.get('sha256')!r}"
    # Amandemen 5 C.12: file .md tanpa titik yang belum ada di cakupan baru -> selesai, ada false (seperti T2).
    belum = cek(klien.panggil("baca", path="wiki/konsep/belum-ada.md"), "selesai", "T19 baca belum ada")
    assert belum.get("ada") is False and belum.get("isi") == "" and belum.get("sha256") is None, f"T19: {belum!r}"
    # Amandemen 5 C.5: file non-.md di wiki/ -> `baca` ditolak, tanpa membocorkan isi (ada maupun belum ada).
    for rel in ("wiki/konsep/gambar.png", "wiki/catatan-t19.txt", "wiki/konsep/tanpa-ekstensi"):
        (vault / rel).write_bytes(b"ISI-NON-MD-T19")
    for rel in ("wiki/konsep/gambar.png", "wiki/catatan-t19.txt", "wiki/konsep/tanpa-ekstensi", "wiki/konsep/belum-ada.txt"):
        hasil = klien.panggil("baca", path=rel)
        cek_pesan(hasil, "ditolak", f"T19 baca non-md {rel}")
        assert "ISI-NON-MD-T19" not in json.dumps(hasil, ensure_ascii=False), f"T19 baca {rel}: isi bocor: {hasil!r}"

    sebelum = potret(vault)
    tulis = klien.panggil("tulis", kunci_operasi="ingest: claude-code/-/uji-t19#1",
                          perubahan=[{"path": HALAMAN_UNIK, "isi_baru": "# Ditimpa\n", "hash_lama": sha_file(vault, HALAMAN_UNIK)}],
                          tambahan_log=[], alasan="uji T19")
    cek_pesan(tulis, "ditolak", "T19 tulis halaman pengetahuan")
    baru = klien.panggil("tulis", kunci_operasi="ingest: claude-code/-/uji-t19#2",
                         perubahan=[{"path": "wiki/konsep/baru-t19.md", "isi_baru": "# Baru\n", "hash_lama": None}],
                         tambahan_log=[], alasan="uji T19")
    cek_pesan(baru, "ditolak", "T19 tulis halaman pengetahuan baru")
    kunci = "tangkap: claude-code/-/uji-t19#3"
    log = klien.panggil("tambah_log", path=HALAMAN_UNIK, kunci=kunci,
                        teks=f"\n### 2026-11-18 10:00 · claude-code · - · sesi uji-t19 · potongan\n{kunci}\n- uji\n", alasan="uji T19")
    cek_pesan(log, "ditolak", "T19 tambah_log ke halaman pengetahuan")
    # Amandemen 3 §2: `daftar` tidak diperluas.
    for folder in ("wiki/konsep", "wiki/sumber"):
        cek_pesan(klien.panggil("daftar", folder=folder), "ditolak", f"T19 daftar({folder!r})")
    assert potret(vault) == sebelum, "T19: vault berubah"
    assert not (vault / "wiki/konsep/baru-t19.md").exists()


# -- T20: masukan tidak valid ------------------------------------------------------------

# Amandemen 5 A.2 dan A.6: spasi di awal dan akhir dibuang dulu; panjang sesudahnya harus 1-500 code point.
TIDAK_VALID = [
    ({"kueri": ""}, "kueri kosong"),
    ({"kueri": "   "}, "kueri hanya spasi"),
    ({"kueri": " \t\n "}, "kueri hanya spasi, tab, dan baris baru"),
    ({"kueri": "a" * (BATAS_KUERI + 1)}, "kueri 501 karakter ASCII"),
    ({"kueri": "é" * (BATAS_KUERI + 1)}, "kueri 501 karakter non-ASCII"),
    ({"kueri": "  " + "a" * (BATAS_KUERI + 1) + "  "}, "kueri 501 karakter di antara spasi"),
    ({"kueri": "obligasi", "jumlah": 0}, "jumlah 0"),
    ({"kueri": "obligasi", "jumlah": JUMLAH_MAKS + 1}, "jumlah 11"),
    ({"kueri": "obligasi", "jumlah": -1}, "jumlah -1"),
]

# Amandemen 5 A.7: tipe salah -> `ditolak`, atau galat protokol MCP jika skema menolak sebelum tool berjalan.
# Tidak pernah `selesai` (dan, karena validasi mendahului indeks, tidak pernah `gagal`); server tidak boleh crash.
TIPE_SALAH = [
    ({"kueri": "obligasi", "jumlah": "5"}, "jumlah string"),
    ({"kueri": "obligasi", "jumlah": 5.5}, "jumlah desimal"),
    ({"kueri": "obligasi", "jumlah": None}, "jumlah null"),
    ({"kueri": 123}, "kueri angka"),
    ({"kueri": None}, "kueri null"),
    ({"kueri": ["obligasi"]}, "kueri array"),
]


# Tidak ditetapkan amandemen mana pun (boolean, string numerik berbentuk desimal); hanya dicatat di keluaran tes.
TIPE_TIDAK_DITETAPKAN = [
    ({"kueri": "obligasi", "jumlah": True}, "jumlah boolean true"),
    ({"kueri": "obligasi", "jumlah": "5.0"}, "jumlah string '5.0'"),
]


def nilai_tipe_salah(klien, argumen: dict[str, Any]) -> tuple[str, str | None]:
    """Panggil `cari` dengan masukan bertipe salah. Mengembalikan (bentuk, masalah).

    Bentuk: `ditolak`, `galat-protokol`, `isError`, atau status lain. `masalah` None bila sesuai amandemen 5 A.7
    (`ditolak` berisi hanya status dan pesan, atau galat protokol MCP).
    TAFSIRAN: hasil tool `isError` tanpa JSON status (galat skema dari server) dianggap galat protokol.
    """
    from mcp_klien import GalatMcp

    try:
        hasil = klien.panggil("cari", **argumen)
    except GalatMcp:
        return "galat-protokol", None
    if isinstance(hasil, dict) and hasil.get("_is_error") is True and "status" not in hasil:
        return "isError", None
    if isinstance(hasil, dict) and hasil.get("status") == "ditolak":
        if set(hasil) == {"status", "pesan"} and str(hasil.get("pesan", "")).strip():
            return "ditolak", None
        return "ditolak", f"field {sorted(hasil)}, diharapkan hanya status dan pesan"
    status = hasil.get("status") if isinstance(hasil, dict) else type(hasil).__name__
    return str(status), f"status {status!r}; diharapkan `ditolak` atau galat protokol: {json.dumps(hasil, ensure_ascii=False)[:240]}"


def kumpulkan_tipe_salah(klien, konteks: str, kontrol_sesudah=None) -> tuple[dict[str, str], list[str]]:
    """Jalankan semua TIPE_SALAH, kumpulkan semua pelanggaran (tidak berhenti di yang pertama)."""
    bentuk: dict[str, str] = {}
    pelanggaran: list[str] = []
    for argumen, nama in TIPE_SALAH:
        b, masalah = nilai_tipe_salah(klien, argumen)
        bentuk[nama] = b
        if masalah:
            pelanggaran.append(f"{konteks} {nama}: {masalah}")
        if kontrol_sesudah:
            kontrol_sesudah(nama)
    return bentuk, pelanggaran


def test_t20b_masukan_tidak_valid_didahulukan_dari_indeks_tidak_ada(server, vault_pengetahuan):
    # Amandemen 4 §4: validasi masukan (langkah 1) mendahului pembacaan indeks (langkah 2), jadi kueri
    # tidak valid selalu `ditolak`, walaupun indeks tidak ada. Tidak butuh perintah bangun indeks.
    vault = vault_pengetahuan
    assert not (vault / ".vault-meta").exists(), "fixture: vault tidak boleh punya indeks"
    klien = server()
    sebelum = potret_penuh(vault)
    for argumen, nama in TIDAK_VALID:
        cek_tanpa_hasil(klien.panggil("cari", **argumen), "ditolak", f"T20b {nama} tanpa indeks")
    # Kontrol: kueri sah pada vault yang sama menghasilkan `gagal` (indeks tidak ada), bukan `ditolak`.
    cek_tanpa_hasil(klien.panggil("cari", kueri="obligasi"), "gagal", "T20b kontrol kueri sah tanpa indeks")
    bentuk, pelanggaran = kumpulkan_tipe_salah(klien, "T20b tanpa indeks")
    print(f"\nT20b bentuk penolakan tipe salah: {bentuk}")
    assert potret_penuh(vault) == sebelum, "T20b: vault berubah"
    assert not pelanggaran, "T20b: tipe salah tidak ditolak (amandemen 5 A.7):\n  " + "\n  ".join(pelanggaran)


def test_t20c_tipe_salah_ditolak_atau_galat_protokol_server_tetap_hidup(server, vault_berindeks):
    vault = vault_berindeks
    klien = server()
    sebelum = potret_penuh(vault)
    def kontrol(nama: str) -> None:  # server tidak crash: panggilan sah sesudahnya tetap `selesai`
        cek_hasil_cari(vault, cari(klien, "kalsedon"), f"T20c kontrol sesudah {nama}")

    bentuk, pelanggaran = kumpulkan_tipe_salah(klien, "T20c", kontrol)
    print(f"\nT20c bentuk penolakan tipe salah: {bentuk}")
    # Masukan yang tidak ditetapkan amandemen: hanya dicatat, tidak diuji.
    for argumen, nama in TIPE_TIDAK_DITETAPKAN:
        b, _ = nilai_tipe_salah(klien, argumen)
        print(f"T20c (tidak diuji) {nama}: {b}")
        kontrol(nama)
    assert klien.proc.poll() is None, "T20c: server berhenti"
    assert potret_penuh(vault) == sebelum, "T20c: vault berubah"
    assert not pelanggaran, "T20c: tipe salah tidak ditolak (amandemen 5 A.7):\n  " + "\n  ".join(pelanggaran)


def test_t20d_tipe_salah_dijawab_ditolak_oleh_server(server, vault_berindeks):
    # Fase F, kandidat kedua (permintaan Example User): tipe salah harus dijawab `ditolak` oleh server (hanya status
    # dan pesan), bukan galat skema MCP. Amandemen 5 A.7 sendiri menerima keduanya; pemeriksaan ini lebih ketat
    # daripada T20b/T20c. Termasuk `jumlah` boolean dan string "5.0", yang menurut Hermes kini ditolak
    # ("jumlah hanya menerima bilangan bulat sungguhan").
    vault = vault_berindeks
    klien = server()
    sebelum = potret_penuh(vault)
    bentuk: dict[str, str] = {}
    for argumen, nama in [*TIPE_SALAH, *TIPE_TIDAK_DITETAPKAN]:
        b, masalah = nilai_tipe_salah(klien, argumen)
        bentuk[nama] = b
        cek_hasil_cari(vault, cari(klien, "kalsedon"), f"T20d kontrol sesudah {nama}")  # server tetap hidup
    print(f"\nT20d bentuk penolakan: {bentuk}")
    bukan_ditolak = {n: b for n, b in bentuk.items() if b != "ditolak"}
    assert not bukan_ditolak, f"T20d: harus `ditolak` oleh server, bukan galat skema atau status lain: {bukan_ditolak}"
    assert potret_penuh(vault) == sebelum, "T20d: vault berubah"


def test_t20_kueri_dan_jumlah_tidak_valid_ditolak(server, vault_berindeks):
    # Pada vault berindeks `ditolak` hanya bisa berasal dari validasi masukan; urutan terhadap
    # indeks yang tidak ada diuji di T20b (amandemen 4 §4).
    vault = vault_berindeks
    klien = server()
    sebelum = potret_penuh(vault)
    for argumen, nama in TIDAK_VALID:
        cek_tanpa_hasil(klien.panggil("cari", **argumen), "ditolak", f"T20 {nama}")

    # Kontrol batas: tepat di batas harus diterima. Panjang dihitung dalam code point, bukan byte,
    # dan sesudah spasi di awal dan akhir dibuang (amandemen 5 A.2).
    k500 = ("obligasi é " * 60)[:BATAS_KUERI].strip()
    k500 = k500 + "é" * (BATAS_KUERI - len(k500))
    assert len(k500) == BATAS_KUERI and len(k500.encode("utf-8")) > BATAS_KUERI
    sah = [
        ({"kueri": "a"}, 1, "kueri 1 karakter"),
        ({"kueri": " a "}, 1, "kueri 1 karakter di antara spasi"),
        ({"kueri": k500}, JUMLAH_BAWAAN, "kueri 500 karakter"),
        ({"kueri": "   " + k500 + "   "}, JUMLAH_BAWAAN, "kueri 500 karakter di antara spasi"),
        ({"kueri": "obligasi", "jumlah": 1}, 1, "jumlah 1"),
        ({"kueri": "obligasi", "jumlah": JUMLAH_MAKS}, JUMLAH_MAKS, "jumlah 10"),
    ]
    for argumen, batas, nama in sah:
        cek_hasil_cari(vault, klien.panggil("cari", **argumen), f"T20 kontrol {nama}", batas)
    assert potret_penuh(vault) == sebelum, "T20: vault berubah"


# -- T21: indeks tidak ada atau tidak terbaca ------------------------------------------------

DIR_INDEKS = ".vault-meta/bm25"  # amandemen 4 §6: indeks disimpan di dalam vault


def test_t21a_indeks_tidak_ada_gagal_dengan_pesan(server, vault_pengetahuan):
    vault = vault_pengetahuan
    assert not (vault / DIR_INDEKS).exists(), "fixture: vault tidak boleh punya indeks"
    klien = server()
    sebelum = potret_penuh(vault)
    pesan = cek_tanpa_hasil(cari(klien, "obligasi"), "gagal", "T21a")
    # Amandemen 5 A.9: `pesan` untuk `gagal` wajib memuat kata "Hermes" (indeks perlu disegarkan lewat Hermes).
    assert "hermes" in pesan.lower(), f"T21a: pesan tidak menyebut cara menyegarkan lewat Hermes: {pesan!r}"
    assert potret_penuh(vault) == sebelum, "T21a: `cari` menulis ke vault (membangun indeks sendiri atau berkas lain)"
    assert not (vault / DIR_INDEKS).exists(), "T21a: `cari` membuat indeks sendiri"


@pytest.mark.parametrize("kerusakan", ["dikosongkan", "dihapus"])
def test_t21b_indeks_tidak_terbaca_gagal_dengan_pesan(server, vault_pengetahuan, bangun_indeks, kerusakan):
    import shutil

    vault = vault_pengetahuan
    bangun_indeks(vault)
    akar = vault / DIR_INDEKS
    assert akar.is_dir() and any(p.is_file() for p in akar.rglob("*")), \
        f"T21b: amandemen 4 §6 menyatakan indeks disimpan di {DIR_INDEKS}/, tetapi tidak ada file di sana"
    cek_hasil_cari(vault, cari(server(nama="sebelum-rusak"), "obligasi"), "T21b kontrol sebelum rusak")
    # Merusak berkas hasil perintah Hermes; tes tidak membuat atau meniru format indeks.
    if kerusakan == "dikosongkan":
        for p in akar.rglob("*"):
            if p.is_file():
                p.write_bytes(b"")
    else:
        shutil.rmtree(akar)
    pesan = cek_tanpa_hasil(cari(server(nama=f"sesudah-{kerusakan}"), "obligasi"), "gagal", f"T21b indeks {kerusakan}")
    assert "hermes" in pesan.lower(), f"T21b: pesan tidak menyebut cara menyegarkan lewat Hermes: {pesan!r}"


def penanda_unik(vault: Path, rel: str, cuplikan: str, panjang: int = 24) -> str | None:
    """Potongan ASCII (huruf dan spasi) dari `cuplikan` yang hanya muncul di halaman `rel` di antara semua .md di `wiki/`."""
    semua = {p.relative_to(vault).as_posix(): p.read_bytes().decode("utf-8") for p in (vault / "wiki").rglob("*.md")}
    for m in re.finditer(r"[A-Za-z ]{%d,}" % panjang, cuplikan):
        run = m.group(0)
        for i in range(0, len(run) - panjang + 1):
            w = run[i:i + panjang]
            if w.strip() and sum(1 for isi in semua.values() if w in isi) == 1 and w in semua[rel]:
                return w
    return None


def test_t21c_kerusakan_sebagian_tidak_crash_dan_dilaporkan_basi(server, vault_pengetahuan, bangun_indeks):
    # Amandemen 5 D.21: snapshot utama sah tetapi sebagian chunk rusak -> kandidat terdampak dibuang,
    # `basi: true`, status tetap `selesai`; indeks utama tidak ada/tidak sah -> `gagal`.
    # Tes tidak tahu berkas mana yang utama (format indeks tidak boleh ditiru), jadi tiap berkas di
    # `.vault-meta/bm25/` dikosongkan satu per satu. Hasilnya harus `gagal` (pesan menyebut Hermes) atau
    # `selesai` dengan bentuk sah; tidak pernah galat atau server berhenti.
    # Keputusan Example User (fase F): `basi` hanya diperiksa bila kerusakan menyentuh hasil kueri tes, yaitu
    # ada halaman dari hasil kueri yang dibuang. Dalam kasus itu halaman tersebut harus hilang dari hasil
    # dan `basi` harus true. Jika kerusakan tidak mengubah hasil, nilai `basi` tidak diuji.
    vault = vault_pengetahuan
    bangun_indeks(vault)
    akar = vault / DIR_INDEKS
    berkas = sorted(p for p in akar.rglob("*") if p.is_file())
    assert berkas, f"T21c: tidak ada file di {DIR_INDEKS}/"
    dasar = cek_hasil_cari(vault, cari(server(nama="dasar"), "obligasi", jumlah=JUMLAH_MAKS), "T21c dasar", JUMLAH_MAKS)
    halaman_dasar = set(paths_dari(dasar))
    assert halaman_dasar == set(HALAMAN_OBLIGASI), f"T21c: hasil dasar {sorted(halaman_dasar)}"
    asli = {p: p.read_bytes() for p in berkas}
    hasil_per_berkas: dict[str, str] = {}
    menyentuh_hasil = 0
    for p in berkas:
        nama = p.relative_to(akar).as_posix()
        p.write_bytes(b"")
        try:
            hasil = cari(server(nama=f"rusak-{len(hasil_per_berkas)}"), "obligasi", jumlah=JUMLAH_MAKS)
        finally:
            p.write_bytes(asli[p])
        assert isinstance(hasil, dict) and hasil.get("status") in ("selesai", "gagal"), \
            f"T21c berkas {nama} dikosongkan: hasil tidak sah: {hasil!r}"
        if hasil["status"] == "gagal":
            pesan = cek_tanpa_hasil(hasil, "gagal", f"T21c {nama}")
            assert "hermes" in pesan.lower(), f"T21c {nama}: pesan tidak menyebut Hermes: {pesan!r}"
            hasil_per_berkas[nama] = "gagal"
            continue
        items = cek_hasil_cari(vault, hasil, f"T21c {nama}", JUMLAH_MAKS)
        sisa = set(paths_dari(items))
        assert sisa <= halaman_dasar, f"T21c {nama}: muncul halaman di luar hasil dasar: {sorted(sisa - halaman_dasar)}"
        dibuang = halaman_dasar - sisa
        if dibuang:
            menyentuh_hasil += 1
            assert hasil["indeks"]["basi"] is True, (
                f"T21c: berkas {nama} dikosongkan, halaman {sorted(dibuang)} dibuang dari hasil, "
                f"tetapi basi bukan true: {hasil['indeks']!r}")
            hasil_per_berkas[nama] = f"selesai, dibuang {len(dibuang)}, basi true"
        else:
            hasil_per_berkas[nama] = f"selesai, hasil tidak berubah (basi {hasil['indeks']['basi']} tidak diuji)"
    print(f"\nT21c hasil per berkas indeks: {json.dumps(hasil_per_berkas, ensure_ascii=False, indent=1)}")

    # Tahap 2: kerusakan di dalam berkas indeks, hanya pada bagian milik satu halaman yang muncul di hasil
    # kueri. Tes tidak mengurai format indeks: teks kutipan halaman itu (unik di seluruh vault) dicari sebagai
    # byte di semua berkas di bawah `.vault-meta/` (kecuali catatan operasi guard, `hermes-windows/`) lalu
    # ditimpa dengan huruf lain yang panjangnya sama (JSON tetap sah, hash chunk tidak cocok). Teks chunk
    # halaman ternyata disimpan di `.vault-meta/chunks/`, bukan di `.vault-meta/bm25/` (temuan fase F).
    # Jika teks itu tidak ditemukan di mana pun, halaman itu dilewati.
    meta = vault / ".vault-meta"
    isi_meta = {p: p.read_bytes() for p in meta.rglob("*")
                if p.is_file() and "hermes-windows" not in p.relative_to(meta).parts}
    per_halaman: dict[str, str] = {}
    for item in dasar:
        rel = item["path"]
        penanda = penanda_unik(vault, rel, item["cuplikan"])
        if penanda is None:
            per_halaman[rel] = "dilewati: tidak ada kutipan unik"
            continue
        kena = {p: b for p, b in isi_meta.items() if penanda.encode("utf-8") in b}
        if not kena:
            per_halaman[rel] = "dilewati: kutipan tidak ditemukan di berkas indeks"
            continue
        # Dua cara merusak bagian milik halaman ini: teksnya ditimpa (hash tidak cocok) atau berkasnya dikosongkan.
        for varian in ("ditimpa", "dikosongkan"):
            kunci = f"{rel} [{varian}, {len(kena)} berkas]"
            for p, b in kena.items():
                p.write_bytes(b.replace(penanda.encode("utf-8"), b"Q" * len(penanda.encode("utf-8")))
                              if varian == "ditimpa" else b"")
            try:
                hasil = cari(server(nama=f"halaman-{len(per_halaman)}"), "obligasi", jumlah=JUMLAH_MAKS)
            finally:
                for p, b in kena.items():
                    p.write_bytes(b)
            assert isinstance(hasil, dict) and hasil.get("status") in ("selesai", "gagal"), \
                f"T21c {kunci} dirusak: hasil tidak sah: {hasil!r}"
            if hasil["status"] == "gagal":
                pesan = cek_tanpa_hasil(hasil, "gagal", f"T21c {kunci}")
                assert "hermes" in pesan.lower(), f"T21c {kunci}: pesan tidak menyebut Hermes: {pesan!r}"
                per_halaman[kunci] = "gagal"
                continue
            items = cek_hasil_cari(vault, hasil, f"T21c {kunci}", JUMLAH_MAKS)
            sisa = set(paths_dari(items))
            assert sisa <= halaman_dasar, f"T21c {kunci}: muncul halaman di luar hasil dasar: {sorted(sisa - halaman_dasar)}"
            dibuang = halaman_dasar - sisa
            if not dibuang:
                per_halaman[kunci] = f"selesai, hasil tidak berubah (basi {hasil['indeks']['basi']} tidak diuji)"
                continue
            menyentuh_hasil += 1
            assert dibuang == {rel}, f"T21c {kunci}, tetapi yang dibuang {sorted(dibuang)}"
            assert hasil["indeks"]["basi"] is True, (
                f"T21c: bagian indeks milik {rel} dirusak ({varian}), halaman itu dibuang dari hasil, "
                f"tetapi basi bukan true: {hasil['indeks']!r}")
            per_halaman[kunci] = "selesai, halaman dibuang, basi true"
    stage2 = sum(1 for v in per_halaman.values() if v.startswith("selesai, halaman dibuang") or v == "gagal")
    if not stage2:
        print("T21c TAHAP 2 TIDAK KONKLUSIF: kerusakan pada berkas milik halaman tidak menyentuh hasil kueri; "
              "nilai basi tidak diuji (sesuai keputusan Example User).")
    print(f"T21c hasil per halaman (kerusakan di berkas `.vault-meta/` yang memuat kutipan halaman): "
          f"{json.dumps(per_halaman, ensure_ascii=False, indent=1)}")
    # Setelah dipulihkan, indeks utuh kembali menghasilkan hasil dasar.
    pulih = cek_hasil_cari(vault, cari(server(nama="pulih"), "obligasi", jumlah=JUMLAH_MAKS), "T21c pulih", JUMLAH_MAKS)
    assert set(paths_dari(pulih)) == halaman_dasar
    if not menyentuh_hasil and "gagal" not in hasil_per_berkas.values():
        pytest.skip("T21c tidak konklusif: tidak ada berkas indeks yang kerusakannya menyentuh hasil kueri "
                    f"(hasil per berkas: {hasil_per_berkas})")


# -- T22: folder bertitik ditolak ---------------------------------------------------------

def test_t22_baca_folder_bertitik_ditolak(server, vault_pengetahuan):
    vault = vault_pengetahuan
    penanda = "RAHASIA-T22"
    berkas = [
        ".vault-meta/catatan.md",
        ".vault-meta/sub/dalam.md",
        ".obsidian/catatan.md",
        "wiki/.tersembunyi/rahasia.md",
        "wiki/sesi/.arsip/lama.md",
        "sesi-log/.cadangan/profil-log.md",
    ]
    for rel in berkas:
        (vault / rel).parent.mkdir(parents=True, exist_ok=True)
        (vault / rel).write_bytes(f"# {penanda}\n".encode("utf-8"))
    kasus = [
        *berkas,
        "wiki/../.vault-meta/catatan.md",
        "wiki/konsep/../../.vault-meta/catatan.md",
        ".VAULT-META/catatan.md",
        ".vault-meta\\catatan.md",
    ]
    klien = server()
    for rel in kasus:
        hasil = klien.panggil("baca", path=rel)
        cek_pesan(hasil, "ditolak", f"T22 baca {rel}")
        assert penanda not in json.dumps(hasil, ensure_ascii=False), f"T22 baca {rel}: isi file bocor: {hasil!r}"
    # Kontrol: halaman pengetahuan biasa di folder yang sama tetap terbaca.
    cek(klien.panggil("baca", path=HALAMAN_UNIK), "selesai", "T22 kontrol")


# Amandemen 4 §5: setiap komponen path yang diawali titik (folder maupun file) ditolak di semua cakupan.
FILE_BERTITIK = [
    "wiki/sesi/.tersembunyi.md",
    "wiki/profil/.catatan.md",
    "wiki/konsep/.draft.md",
    "sesi-log/.log.md",
    "wiki/.tersembunyi.md",
]


def test_t22b_baca_file_bertitik_ditolak(server, vault_pengetahuan):
    vault = vault_pengetahuan
    penanda = "RAHASIA-T22B"
    for rel in FILE_BERTITIK:
        (vault / rel).parent.mkdir(parents=True, exist_ok=True)
        (vault / rel).write_bytes(f"# {penanda}\n".encode("utf-8"))
    klien = server()
    for rel in FILE_BERTITIK:
        hasil = klien.panggil("baca", path=rel)
        cek_pesan(hasil, "ditolak", f"T22b baca {rel}")
        assert penanda not in json.dumps(hasil, ensure_ascii=False), f"T22b baca {rel}: isi file bocor: {hasil!r}"
    # Amandemen 5 C.16: file bertitik yang belum ada -> `ditolak`; aturan titik diperiksa sebelum keberadaan file.
    for rel in ("wiki/sesi/.belum-ada.md", "wiki/konsep/.belum-ada.md", "sesi-log/.belum-ada-log.md"):
        cek_pesan(klien.panggil("baca", path=rel), "ditolak", f"T22b baca file bertitik yang belum ada: {rel}")
    # Kontrol: file tanpa titik di folder yang sama tetap terbaca.
    cek(klien.panggil("baca", path="wiki/sesi/_index.md"), "selesai", "T22b kontrol")


def test_t22d_daftar_tidak_menampilkan_entri_bertitik(server, vault_pengetahuan):
    # Amandemen 5 C.15: entri bertitik tidak ditampilkan oleh `daftar`.
    vault = vault_pengetahuan
    bertitik = ["wiki/sesi/.tersembunyi.md", "wiki/sesi/.arsip/lama.md", "wiki/profil/.catatan.md",
                "sesi-log/.log.md", "sesi-log/.cadangan/profil-log.md"]
    for rel in bertitik:
        (vault / rel).parent.mkdir(parents=True, exist_ok=True)
        (vault / rel).write_bytes(b"# Bertitik\n")
    klien = server()
    wajib = {"wiki/sesi": "wiki/sesi/_index.md", "wiki/profil": "wiki/profil/profil.md", "sesi-log": "sesi-log/profil-log.md"}
    for folder, ada in wajib.items():
        hasil = klien.panggil("daftar", folder=folder)
        assert isinstance(hasil, list), f"T22d daftar({folder!r}): {hasil!r}"
        paths = [i.get("path") for i in hasil]
        bocor = [p for p in paths if any(k.startswith(".") for k in p.split("/"))]
        assert not bocor, f"T22d daftar({folder!r}) menampilkan entri bertitik: {bocor}"
        assert ada in paths, f"T22d daftar({folder!r}): kontrol {ada} hilang: {paths}"


def test_t22c_tulis_ke_path_bertitik_ditolak(server, vault_pengetahuan):
    vault = vault_pengetahuan
    ada = "wiki/sesi/.tersembunyi.md"
    (vault / ada).write_bytes(b"# Ada\n")
    klien = server()
    sebelum = potret_penuh(vault)
    isi_log = "---\ntitle: Log uji\ntype: sesi-log\n---\n\n# Log uji\n"
    kasus = [
        (ada, sha_file(vault, ada)),                      # menimpa file bertitik yang ada
        ("wiki/sesi/.baru.md", None),
        ("wiki/profil/.baru.md", None),
        ("wiki/sesi/.arsip/baru.md", None),               # folder bertitik di dalam cakupan lama
        ("sesi-log/.baru-log.md", None),                  # file Log baru
        ("sesi-log/.cadangan/baru-log.md", None),
        ("wiki/konsep/.baru.md", None),                   # cakupan pengetahuan: ditolak juga karena baca-saja
    ]
    for i, (rel, h) in enumerate(kasus):
        isi = isi_log if rel.startswith("sesi-log/") else "# Uji T22c\n"
        hasil = klien.panggil("tulis", kunci_operasi=f"ingest: claude-code/-/uji-t22c-{i}#1-2",
                              perubahan=[{"path": rel, "isi_baru": isi, "hash_lama": h}],
                              tambahan_log=[], alasan="uji T22c")
        cek_pesan(hasil, "ditolak", f"T22c tulis {rel}")
    # `tambah_log` juga penulisan: komponen bertitik ditolak walau foldernya `sesi-log/`.
    for i, rel in enumerate(["sesi-log/.log.md", "sesi-log/.cadangan/profil-log.md"]):
        kunci = f"tangkap: claude-code/-/uji-t22c-log{i}#1-2"
        teks = f"\n### 2026-11-18 10:00 · claude-code · - · sesi uji-t22c · potongan\n{kunci}\n- uji\n"
        cek_pesan(klien.panggil("tambah_log", path=rel, kunci=kunci, teks=teks, alasan="uji T22c"),
                  "ditolak", f"T22c tambah_log {rel}")
    assert potret_penuh(vault) == sebelum, "T22c: vault berubah"
    # Kontrol: penulisan sah (tanpa komponen bertitik) di folder yang sama tetap diterima.
    sah = klien.panggil("tulis", kunci_operasi="ingest: claude-code/-/uji-t22c-kontrol#1-2",
                        perubahan=[{"path": "wiki/sesi/uji-t22c-sah.md", "isi_baru": "# Sah\n", "hash_lama": None}],
                        tambahan_log=[], alasan="uji T22c kontrol")
    cek(sah, "selesai", "T22c kontrol")


# -- T23: cari saat indeks dipublikasikan ulang ---------------------------------------------

T23_STABIL = "wiki/konsep/uji-t23-stabil.md"   # tidak pernah berubah; ada di snapshot lama maupun baru
T23_KATA = "beril"


def _t23_churn(versi: int) -> str:
    return f"wiki/konsep/uji-t23-c{versi}.md"


def _tulis_t23(vault: Path, versi: int, retry: list[int] | None = None) -> None:
    """Halaman churn versi `versi` ditambah dan versi sebelumnya dihapus, sehingga perintah bangun indeks
    benar-benar menerbitkan snapshot baru. Halaman stabil tidak disentuh.

    Di Windows, penghapusan bisa gagal (WinError 32) selama server `cari` masih memegang berkas halaman itu
    (temuan fase F). Penghapusan diulang sampai 10 detik; jumlah pengulangan dicatat di `retry`.
    """
    (vault / _t23_churn(versi)).write_bytes(
        f"---\ntitle: Uji T23 C{versi}\ntype: konsep\n---\n\n# Uji T23 C{versi}\n\nVersi {versi}. Kata: {T23_KATA}.\n".encode("utf-8"))
    lama = vault / _t23_churn(versi - 1)
    batas = time.monotonic() + 10
    while versi > 0 and lama.exists():
        try:
            lama.unlink()
            break
        except PermissionError:
            if retry is not None:
                retry.append(versi)
            if time.monotonic() > batas:
                raise
            time.sleep(0.05)


def test_t23_cari_saat_indeks_dipublikasikan_ulang(server, vault_pengetahuan, bangun_indeks):
    # Amandemen 5 D.14: "publikasi ulang" = perintah bangun indeks berjalan bersamaan dengan rangkaian `cari`;
    # setiap panggilan wajib `selesai` dari snapshot lama atau baru, tidak pernah error baca.
    # Halaman yang diubah atau dihapus sebelum snapshot baru terbit boleh dibuang oleh filter kesegaran
    # (terbukti di uji awal fase F), jadi tes tidak mensyaratkan halaman churn muncul. Yang disyaratkan:
    # halaman stabil (tidak berubah, ada di kedua snapshot) selalu muncul, dan hasilnya selalu sah.
    vault = vault_pengetahuan
    (vault / T23_STABIL).write_bytes(
        f"---\ntitle: Uji T23 Stabil\ntype: konsep\n---\n\n# Uji T23 Stabil\n\nHalaman stabil. Kata: {T23_KATA}.\n".encode("utf-8"))
    _tulis_t23(vault, 0)
    bangun_indeks(vault)
    klien = server()
    awal = cek_hasil_cari(vault, cari(klien, T23_KATA), "T23 awal")
    assert sorted(paths_dari(awal)) == sorted([T23_STABIL, _t23_churn(0)]), f"T23 awal: {paths_dari(awal)}"

    putaran = int(os.environ.get("MEMORI_GUARD_T23_PUTARAN", "6"))
    bangun: list[tuple[float, float, int, str]] = []
    galat_thread: list[str] = []
    retry_hapus: list[int] = []
    selesai = threading.Event()

    def pembangun() -> None:
        try:
            for versi in range(1, putaran + 1):
                _tulis_t23(vault, versi, retry_hapus)
                t0 = time.monotonic()
                proses = jalankan_bangun_indeks(vault)
                bangun.append((t0, time.monotonic(), proses.returncode,
                               proses.stderr.decode("utf-8", "replace")[-2000:]))
                if proses.returncode not in KODE_BANGUN_BERHASIL:
                    return
        except BaseException as exc:  # jangan mati diam-diam: dilaporkan sebagai masalah
            galat_thread.append(f"thread pembangun berhenti di publikasi ke-{len(bangun) + 1}: {type(exc).__name__}: {exc}")
        finally:
            selesai.set()

    benang = threading.Thread(target=pembangun, daemon=True)
    benang.start()
    panggilan: list[tuple[float, float, Any]] = []
    while not selesai.is_set():
        t0 = time.monotonic()
        try:
            h: Any = cari(klien, T23_KATA)
        except Exception as exc:  # galat JSON-RPC atau respons hilang = kegagalan T23
            h = exc
        panggilan.append((t0, time.monotonic(), h))
    benang.join(timeout=60)

    # Kumpulkan semua masalah (panggilan `cari` dan perintah bangun indeks) supaya satu tidak menutupi yang lain.
    masalah: list[str] = []
    sah_churn = {_t23_churn(v) for v in range(putaran + 1)}
    for i, (_t0, _t1, h) in enumerate(panggilan):
        if isinstance(h, Exception):
            masalah.append(f"cari #{i}: {type(h).__name__}: {h}")
            continue
        try:
            items = cek_hasil_cari(vault, h, f"T23 panggilan {i}", ringan=True)
            paths = set(paths_dari(items))
            assert T23_STABIL in paths, f"T23 panggilan {i}: halaman stabil hilang dari hasil: {sorted(paths)}"
            assert paths <= {T23_STABIL} | sah_churn, f"T23 panggilan {i}: halaman tak dikenal: {sorted(paths)}"
        except AssertionError as exc:
            masalah.append(str(exc)[:400])
    gagal_bangun = [b for b in bangun if b[2] not in KODE_BANGUN_BERHASIL]
    for b in gagal_bangun:
        akhir_stderr = b[3].strip().splitlines()[-1] if b[3].strip() else "(stderr kosong)"
        masalah.append(f"perintah bangun indeks keluar dengan kode {b[2]} (publikasi ke-{bangun.index(b) + 1} dari {putaran}): {akhir_stderr[:300]}")
    masalah.extend(galat_thread)
    print(f"\nT23: {len(panggilan)} panggilan cari, {len(bangun)} publikasi dijalankan dari {putaran}, "
          f"{len(masalah)} masalah, {len(retry_hapus)} pengulangan hapus halaman (dipegang server)")
    assert not masalah, "T23:\n  " + "\n  ".join(masalah)

    # Hasil akhir dibandingkan dengan halaman yang benar-benar ada di disk, bukan dengan asumsi: di scratch G:
    # (Google Drive) halaman yang sudah dihapus kadang tetap terlihat (temuan fase F).
    ada_di_disk = sorted(p for p in [T23_STABIL, *[_t23_churn(v) for v in range(putaran + 1)]] if (vault / p).is_file())
    if ada_di_disk != sorted([T23_STABIL, _t23_churn(putaran)]):
        print(f"T23: peringatan lingkungan, halaman di disk setelah semua publikasi: {ada_di_disk}")
    akhir = cek_hasil_cari(vault, cari(klien, T23_KATA), "T23 akhir")
    assert sorted(paths_dari(akhir)) == ada_di_disk, f"T23 akhir: hasil {paths_dari(akhir)}, di disk {ada_di_disk}"

    tumpang = sum(1 for c0, c1, _ in panggilan for b0, b1, _rc, _e in bangun if c0 < b1 and b0 < c1)
    if tumpang == 0:
        pytest.skip(f"T23 tidak konklusif: {len(panggilan)} panggilan `cari` tidak ada yang bersamaan dengan "
                    f"{len(bangun)} publikasi indeks")
    print(f"\nT23: {len(panggilan)} panggilan cari, {len(bangun)} publikasi, {tumpang} tumpang tindih")

# -- cari saat ada operasi tertunda (amandemen 5 D.13) -----------------------------------------

def test_t23b_cari_tetap_berjalan_saat_ada_operasi_tertunda(server, vault_pengetahuan, bangun_indeks):
    # Sama seperti `baca` dan `daftar` (amandemen 2 §9): selama ada operasi `gagal` yang belum dipulihkan,
    # `cari` berjalan normal walaupun tulis dan tambah_log menjawab `terkunci`.
    from conftest import byte_file, sha_byte
    from test_acceptance_write import (LOG_PROFIL, PROFIL, cek_gagal_dengan_id, cek_terkunci_oleh, entri_log,
                                   panggil_bisa_putus, tambah_fakta, tambahan, perubahan)

    vault = vault_pengetahuan
    bangun_indeks(vault)
    p0 = byte_file(vault, PROFIL)
    p1 = tambah_fakta(p0.decode("utf-8"), "- Fakta T23b.").encode("utf-8")
    kunci = "sinkron: claude-code/-/c-uji-t23b/aaaa023b"
    permintaan = dict(kunci_operasi=kunci, perubahan=[perubahan(PROFIL, p1.decode("utf-8"), sha_byte(p0))],
                      tambahan_log=[tambahan(LOG_PROFIL, kunci, entri_log(kunci, "profil"))], alasan="uji T23b")
    rusak = server(fault="henti_setelah_target_pertama", nama="rusak")
    hasil = panggil_bisa_putus(rusak, "tulis", **permintaan)
    if hasil is not None:
        cek_gagal_dengan_id(hasil, "T23b panggilan pertama")
    rusak.tunggu_berhenti()

    baru = server(nama="baru")
    op_id = cek_gagal_dengan_id(baru.panggil("tulis", **permintaan), "T23b pengulangan")
    lain = dict(kunci_operasi="ingest: claude-code/-/c-uji-t23b-lain#1-2",
                perubahan=[perubahan("wiki/sesi/uji-t23b-lain.md", "# Lain\n", None)], tambahan_log=[], alasan="uji T23b")
    cek_terkunci_oleh(baru.panggil("tulis", **lain), op_id, "T23b tulis saat tertunda")
    tertunda = potret_penuh(vault)
    # `cari` tidak terkunci. Indeks dibangun sebelum operasi tertunda, jadi `basi` boleh true atau false.
    cek_hasil_cari(vault, cari(baru, "obligasi", jumlah=JUMLAH_MAKS), "T23b cari saat tertunda", JUMLAH_MAKS)
    baru.tutup()
    restart = server(nama="restart")
    cek_hasil_cari(vault, cari(restart, "obligasi", jumlah=JUMLAH_MAKS), "T23b cari setelah restart", JUMLAH_MAKS)
    cek_terkunci_oleh(restart.panggil("tulis", **lain), op_id, "T23b tulis masih terkunci setelah restart")
    assert potret_penuh(vault) == tertunda, "T23b: `cari` mengubah vault"
