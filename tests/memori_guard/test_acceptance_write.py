"""Uji penerimaan kotak hitam untuk server MCP `memori-guard`.

Acuan, dari yang paling berlaku: `amandemen-kontrak-1.md`, lalu
`spesifikasi-memori-guard.md` v4 (smoke test T1–T14), lalu
`kontrak-implementasi.md` (mode uji, `--pulihkan`, T15–T16). T17 berasal dari
amandemen E.18. Tafsiran yang masih terbuka ditandai `TAFSIRAN:` dan dirangkum
di `LAPORAN-TES-SIAP.md`.

Tes ini tidak mengimpor kode Hermes; server dan pemeriksa validasi dijalankan
sebagai proses terpisah.
"""

from __future__ import annotations

import hashlib
import json
import random
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from conftest import byte_file, potret, sha_byte, sha_file
from mcp_klien import KlienMcp, ResponsHilang, folder_scratch_izin, jalankan_periksa, jalankan_pulihkan, perintah_python

PROFIL = "wiki/profil/profil.md"
INDEKS_SESI = "wiki/sesi/_index.md"
LOG_PROFIL = "sesi-log/profil-log.md"
KONVENSI = "_konvensi-memori.md"
HASH_SALAH = "sha256:" + "0" * 64
KUNCI_HASIL = {"status", "operation_id", "guarantee_level", "paths", "pesan"}
BATAS_ULANG_PEMEGANG = 30.0  # detik: batas total percobaan ulang pemegang kunci di T8


# -- pembantu ------------------------------------------------------------------

def entri_log(kunci: str, jenis: str = "akhir-sesi", isi: str = "- Catatan uji — dengan karakter non-ASCII ·") -> str:
    """Teks entri Log sesuai konvensi bagian 6: diawali baris kosong, memuat `kunci`."""
    return f"\n### 2026-11-16 10:00 · claude · - · sesi c-20261116-1000-uji1 · {jenis}\n{kunci}\n{isi}\n"


def tambahan(path: str, kunci: str, teks: str | None = None) -> dict[str, str]:
    return {"path": path, "kunci": kunci, "teks": teks if teks is not None else entri_log(kunci)}


def perubahan(path: str, isi_baru: str, hash_lama: str | None) -> dict[str, Any]:
    return {"path": path, "isi_baru": isi_baru, "hash_lama": hash_lama}


def teks_file(vault: Path, rel: str) -> str:
    return (vault / rel).read_bytes().decode("utf-8")


def tambah_fakta(teks: str, fakta: str) -> str:
    """Isi baru profil: ganti placeholder bagian Lainnya dengan satu fakta."""
    lama = "## Lainnya\n\n- Belum ada fakta tercatat.\n"
    if lama in teks:
        return teks.replace(lama, f"## Lainnya\n\n{fakta}\n")
    return teks.rstrip("\n") + f"\n{fakta}\n"


def cek(hasil: Any, status: str, konteks: str = "") -> dict[str, Any]:
    assert isinstance(hasil, dict), f"{konteks}: hasil bukan objek JSON: {hasil!r}"
    assert hasil.get("status") == status, f"{konteks}: status {hasil.get('status')!r}, diharapkan {status!r}; hasil={hasil!r}"
    return hasil


def cek_gagal_dengan_id(hasil: Any, konteks: str) -> str:
    cek(hasil, "gagal", konteks)
    op_id = hasil.get("operation_id")
    assert isinstance(op_id, str) and op_id.strip(), f"{konteks}: `gagal` tanpa operation_id: {hasil!r}"
    return op_id


def cek_terkunci_oleh(hasil: Any, op_id: str, konteks: str) -> None:
    """Amandemen A.2: selama ada operasi gagal/parsial, `pesan` menyebut operation_id-nya."""
    cek(hasil, "terkunci", konteks)
    assert op_id in str(hasil.get("pesan", "")), f"{konteks}: pesan tidak menyebut {op_id}: {hasil!r}"


def norm_paths(hasil: dict[str, Any]) -> list[str]:
    return list(hasil.get("paths") or [])


def hitung(data: bytes, kunci: str) -> int:
    return data.decode("utf-8").count(kunci)


def panggil_bisa_putus(klien: KlienMcp, tool: str, **argumen: Any) -> Any:
    """Untuk fault `henti_*`: kembalikan None jika server berhenti sebelum menjawab."""
    try:
        return klien.panggil(tool, **argumen)
    except ResponsHilang:
        return None


def pulihkan(vault: Path, op_id: str) -> dict[str, Any]:
    """Amandemen A.5: stdout JSON `{operation_id, hasil, paths}`, kode keluar 0."""
    proses = jalankan_pulihkan(vault, op_id)
    keluaran = proses.stdout.decode("utf-8", "replace")
    assert proses.returncode == 0, (
        f"--pulihkan {op_id} keluar dengan kode {proses.returncode}\n"
        f"stdout: {keluaran}\nstderr: {proses.stderr.decode('utf-8', 'replace')}")
    try:
        hasil = json.loads(keluaran)
    except json.JSONDecodeError as exc:
        raise AssertionError(f"--pulihkan tidak menulis JSON ke stdout: {keluaran!r}") from exc
    assert isinstance(hasil, dict), f"--pulihkan: {hasil!r}"
    assert hasil.get("operation_id") == op_id, f"--pulihkan: operation_id {hasil.get('operation_id')!r}"
    assert hasil.get("hasil") in ("diselesaikan", "dikembalikan"), f"--pulihkan: hasil {hasil.get('hasil')!r}"
    assert isinstance(hasil.get("paths"), list), f"--pulihkan: paths {hasil.get('paths')!r}"
    return hasil


def uji_pulihkan_dan_ulang(server, vault: Path, op_id: str, permintaan: dict[str, Any],
                           target_baru: dict[str, bytes | None], target_lama: dict[str, bytes | None],
                           konteks: str) -> None:
    """Pulihkan, cek konsistensi semua target, lalu cek pengulangan sesuai amandemen A.5."""
    hasil = pulihkan(vault, op_id)
    sekarang = {rel: byte_file(vault, rel) for rel in target_baru}
    assert set(hasil["paths"]) == set(target_baru), f"{konteks}: paths --pulihkan {hasil['paths']!r}"
    klien = server(nama="ulang")
    if hasil["hasil"] == "diselesaikan":
        assert sekarang == target_baru, f"{konteks}: `diselesaikan` tetapi tidak semua target baru"
        cek(klien.panggil("tulis", **permintaan), "sudah_ada", f"{konteks}: pengulangan setelah diselesaikan")
        assert {rel: byte_file(vault, rel) for rel in target_baru} == target_baru
    else:
        assert sekarang == target_lama, f"{konteks}: `dikembalikan` tetapi tidak semua target lama"
        cek(klien.panggil("tulis", **permintaan), "selesai", f"{konteks}: pengulangan setelah dikembalikan")
        assert {rel: byte_file(vault, rel) for rel in target_baru} == target_baru


# -- T0: kontrak tool ------------------------------------------------------------

def test_t00_tool_tersedia(server):
    nama = set(server().daftar_tool())
    assert {"daftar", "baca", "tulis", "tambah_log"} <= nama, f"tool yang tersedia: {sorted(nama)}"


# -- T1–T14: smoke test spesifikasi v4 -----------------------------------------------

def test_t01_daftar_wiki_sesi_mengembalikan_index(server, vault):
    # Amandemen B.6: array, path relatif vault dengan `/`, rekursif, hanya .md, urut alfabetis.
    (vault / "wiki/sesi/sub").mkdir()
    (vault / "wiki/sesi/sub/zeta.md").write_bytes(b"# Zeta\n")
    (vault / "wiki/sesi/alfa.md").write_bytes(b"# Alfa\n")
    (vault / "wiki/sesi/bukan-markdown.txt").write_bytes(b"x")
    klien = server()
    hasil = klien.panggil("daftar", folder="wiki/sesi")
    assert isinstance(hasil, list), f"`daftar` harus mengembalikan array: {hasil!r}"
    paths = [i.get("path") for i in hasil]
    assert paths == ["wiki/sesi/_index.md", "wiki/sesi/alfa.md", "wiki/sesi/sub/zeta.md"], f"T1: {paths!r}"
    assert paths == sorted(paths)  # amandemen 2 §6: titik kode Unicode, peka huruf
    for item in hasil:
        assert item.get("ukuran_byte") == (vault / item["path"]).stat().st_size, f"T1: ukuran {item!r}"
    # Amandemen 2 §5: folder di luar cakupan -> {status: ditolak, pesan}.
    for folder in ("wiki", "wiki/meta", "../sesi-log", "Wiki/Sesi", "wiki\\sesi"):
        tolak = klien.panggil("daftar", folder=folder)
        cek(tolak, "ditolak", f"T1 daftar({folder!r})")
        assert tolak.get("pesan"), f"T1 daftar({folder!r}): pesan kosong: {tolak!r}"


def test_t02_baca_ada_belum_ada_dan_konvensi(server, vault):
    klien = server()
    for rel in (PROFIL, KONVENSI):
        hasil = klien.panggil("baca", path=rel)
        cek(hasil, "selesai", f"baca {rel}")  # amandemen 2 §5
        assert hasil.get("ada") is True, f"baca {rel}: {hasil!r}"
        assert hasil.get("isi") == teks_file(vault, rel), f"baca {rel}: isi tidak sama byte per byte"
        assert hasil.get("sha256") == sha_file(vault, rel), f"baca {rel}: hash {hasil.get('sha256')!r}"
        assert hasil.get("path") == rel

    belum = cek(klien.panggil("baca", path="wiki/sesi/belum-ada.md"), "selesai", "baca file belum ada")
    assert belum.get("ada") is False, f"{belum!r}"
    assert belum.get("isi") == "", f"{belum!r}"
    assert "sha256" in belum and belum["sha256"] is None, f"{belum!r}"


def test_t03_tulis_file_baru_selesai_dan_baca_balik(server, vault):
    klien = server()
    rel = "wiki/sesi/uji-t03.md"
    isi = "---\ntitle: Uji T03\ntype: sesi\n---\n\n# Uji T03\n\n- Baris — non-ASCII ·\n"
    hasil = klien.panggil("tulis", kunci_operasi="ingest: claude/-/c-uji-t03#1-2",
                          perubahan=[perubahan(rel, isi, None)], tambahan_log=[], alasan="uji T3")
    cek(hasil, "selesai", "T3")
    assert KUNCI_HASIL <= set(hasil), f"T3: kunci hasil kurang: {hasil!r}"
    assert isinstance(hasil["operation_id"], str) and hasil["operation_id"]
    assert hasil["guarantee_level"], f"T3: guarantee_level kosong: {hasil!r}"
    assert norm_paths(hasil) == [rel], f"T3: paths {hasil['paths']!r}"
    assert byte_file(vault, rel) == isi.encode("utf-8")
    balik = cek(klien.panggil("baca", path=rel), "selesai", "T3 baca balik")
    assert balik["ada"] is True and balik["isi"] == isi and balik["sha256"] == sha_byte(isi.encode("utf-8"))


def test_t04_hash_lama_salah_berubah_tanpa_tulis(server, vault):
    klien = server()
    sebelum = potret(vault)
    hasil = klien.panggil(
        "tulis", kunci_operasi="ingest: claude/-/c-uji-t04#1-2",
        perubahan=[perubahan(PROFIL, tambah_fakta(teks_file(vault, PROFIL), "- Fakta T4."), HASH_SALAH),
                   perubahan("wiki/sesi/uji-t04.md", "# Uji T04\n", None)],
        tambahan_log=[tambahan(LOG_PROFIL, "ingest: claude/-/c-uji-t04#1-2")],
        alasan="uji T4")
    cek(hasil, "berubah", "T4")
    assert potret(vault) == sebelum, "T4: ada file yang tertulis padahal hasil `berubah`"
    # Amandemen B.7: `hash_terkini` hanya untuk target yang hash-nya tidak cocok.
    assert hasil.get("hash_terkini") == {PROFIL: sha_file(vault, PROFIL)}, f"T4: hash_terkini {hasil.get('hash_terkini')!r}"


def test_t05_perubahan_ke_log_yang_ada_ditolak(server, vault):
    # Amandemen C.10: `perubahan` ke Log yang sudah ada selalu `ditolak`, termasuk murni menambah.
    klien = server()
    lama = teks_file(vault, LOG_PROFIL)
    h = sha_file(vault, LOG_PROFIL)
    sebelum = potret(vault)
    kasus = [
        ("ubah satu baris lama", lama.replace("# Log Profil", "# Log Profil (diubah)") + entri_log("id: uji-t05a")),
        ("ubah akhir baris jadi CRLF", lama.replace("\n", "\r\n") + entri_log("id: uji-t05b")),
        ("murni menambah di akhir", lama + entri_log("id: uji-t05c")),
    ]
    for i, (nama, isi_baru) in enumerate(kasus):
        hasil = klien.panggil("tulis", kunci_operasi=f"ingest: claude/-/c-uji-t05-{i}#1-2",
                              perubahan=[perubahan(LOG_PROFIL, isi_baru, h)], tambahan_log=[], alasan="uji T5")
        cek(hasil, "ditolak", f"T5 ({nama})")
        assert "tambahan_log" in str(hasil.get("pesan", "")), f"T5 ({nama}): pesan tidak menyarankan tambahan_log: {hasil!r}"
        assert potret(vault) == sebelum, f"T5 ({nama}): vault berubah"
    # Kontrol: `perubahan` boleh membuat file Log baru.
    baru = "sesi-log/uji-t05-baru-log.md"
    isi = "---\ntitle: Log Uji T05\ntype: sesi-log\ncreated: 2026-11-16\ntags: [sesi-log]\n---\n\n# Log Uji T05\n"
    cek(klien.panggil("tulis", kunci_operasi="ingest: claude/-/c-uji-t05-baru#1-2",
                      perubahan=[perubahan(baru, isi, None)], tambahan_log=[], alasan="uji T5"),
        "selesai", "T5 kontrol: Log baru")
    assert byte_file(vault, baru) == isi.encode("utf-8")


@pytest.mark.parametrize("akhir_baris", ["LF", "CRLF"])
def test_t06_tambah_log_dua_kali_isi_lama_utuh(server, vault, akhir_baris):
    if akhir_baris == "LF":
        rel = LOG_PROFIL
    else:
        # Disiapkan langsung di vault sementara sebelum server berjalan.
        rel = "sesi-log/uji-crlf-log.md"
        (vault / rel).write_bytes(
            "---\r\ntitle: Log Uji CRLF\r\ntype: sesi-log\r\ncreated: 2026-11-16\r\n"
            "tags: [sesi-log]\r\n---\r\n\r\n# Log Uji CRLF\r\n\r\nHanya tambah.\r\n".encode("utf-8"))
    klien = server()
    awal = byte_file(vault, rel)
    e1 = entri_log("tangkap: claude/-/c-uji-t06#1-2", "potongan")
    e2 = entri_log("tangkap: claude/-/c-uji-t06#3-4", "potongan")
    cek(klien.panggil("tambah_log", path=rel, kunci="tangkap: claude/-/c-uji-t06#1-2", teks=e1, alasan="uji T6"),
        "selesai", "T6 entri 1")
    cek(klien.panggil("tambah_log", path=rel, kunci="tangkap: claude/-/c-uji-t06#3-4", teks=e2, alasan="uji T6"),
        "selesai", "T6 entri 2")
    akhir = byte_file(vault, rel)
    assert akhir.startswith(awal), "T6: isi lama tidak utuh byte per byte"
    assert akhir == awal + e1.encode("utf-8") + e2.encode("utf-8"), "T6: hasil bukan isi lama + entri 1 + entri 2"


def test_t07_path_di_luar_cakupan_ditolak(server, vault, ruang_kerja):
    # Disiapkan langsung di vault sementara sebelum server berjalan.
    (vault / "wiki" / "index.md").write_bytes(b"---\ntitle: Index\n---\n\n# Index\n")
    luar = ruang_kerja / "luar-vault"
    luar.mkdir()
    jalur = vault / "wiki" / "sesi" / "jalur"
    buat = subprocess.run(["cmd", "/c", "mklink", "/J", str(jalur), str(luar)], capture_output=True)
    # Batasan lingkungan, bukan perilaku server: junction tidak bisa dibuat di volume non-NTFS lokal
    # (mis. G: Google Drive). Hanya saat berjalan di scratch G: (izin eksplisit) kasus junction dilewati
    # dan dilaporkan; di disk lokal kegagalan membuat junction tetap menggagalkan tes.
    jalur_dibuat = buat.returncode == 0
    if not jalur_dibuat:
        assert folder_scratch_izin() is not None and b"NTFS" in buat.stderr, f"gagal membuat junction: {buat.stderr!r}"

    klien = server()
    sebelum = potret(vault)
    kasus_tulis = [
        ("wiki/index.md", sha_file(vault, "wiki/index.md")),
        (KONVENSI, sha_file(vault, KONVENSI)),
        ("_template-sesi.md", sha_file(vault, "_template-sesi.md")),
        ("wiki/sesi/../profil/uji-t07.md", None),
        ("../uji-t07-luar.md", None),
        ((vault / "wiki" / "sesi" / "uji-t07-absolut.md").as_posix(), None),
        *([("wiki/sesi/jalur/uji-t07.md", None)] if jalur_dibuat else []),
        ("wiki/sesi/uji-t07.txt", None),
        ("WIKI/SESI/_INDEX.md", sha_file(vault, INDEKS_SESI)),   # amandemen C.12: beda huruf
        ("wiki/sesi/_INDEX.md", sha_file(vault, INDEKS_SESI)),   # amandemen C.12: beda huruf
        ("wiki\\sesi\\uji-t07-backslash.md", None),              # amandemen C.12: wajib `/`
        ("wiki\\sesi\\_index.md", sha_file(vault, INDEKS_SESI)),
    ]
    for i, (rel, h) in enumerate(kasus_tulis):
        hasil = klien.panggil("tulis", kunci_operasi=f"ingest: claude/-/c-uji-t07-{i}#1-2",
                              perubahan=[perubahan(rel, "# Uji T07\n", h)], tambahan_log=[], alasan="uji T7")
        cek(hasil, "ditolak", f"T7 tulis {rel}")
    kasus_log = ["wiki/sesi/_index.md", KONVENSI, "sesi-log/../wiki/sesi/_index.md", "sesi-log/jalur-log.txt",
                 "sesi-log\\profil-log.md", "sesi-log/PROFIL-LOG.md"]
    for i, rel in enumerate(kasus_log):
        kunci = f"tangkap: claude/-/c-uji-t07-log{i}#1-2"
        hasil = klien.panggil("tambah_log", path=rel, kunci=kunci, teks=entri_log(kunci, "potongan"), alasan="uji T7")
        cek(hasil, "ditolak", f"T7 tambah_log {rel}")
    assert potret(vault) == sebelum, "T7: vault berubah"
    assert list(luar.iterdir()) == [], "T7: ada file tertulis lewat junction ke luar vault"
    assert not (vault.parent / "uji-t07-luar.md").exists()
    if not jalur_dibuat:
        pytest.skip("T7: semua kasus lain lulus, tetapi kasus junction tidak diuji (volume bukan NTFS lokal)")


def test_t08_penulis_lain_memegang_kunci_terkunci(server, vault):
    # "Hermes memegang kunci" disimulasikan dengan proses server kedua dalam mode uji
    # `tahan_kunci:<detik>`; kunci diambil sebelum inspect (amandemen C.13).
    pemegang = server(fault="tahan_kunci:10", nama="pemegang")
    penulis = server(nama="penulis")
    hasil_pemegang: dict[str, Any] = {}

    polling_selesai = threading.Event()
    mulai = time.monotonic()
    hasil_pemegang["riwayat"] = []

    def jalan() -> None:
        # Pemegang bersaing dengan probe untuk kunci di detik pertama. Jika probe yang lebih dulu
        # memegang kunci, pemegang sah dijawab `terkunci` (tanpa catatan operasi, kontrak §6); dalam
        # kasus itu ia mengulang permintaan yang sama sampai kunci didapat, supaya tes mengukur
        # perilaku "ada penulis yang memegang kunci", bukan siapa yang menang balapan awal.
        # Jeda ulang memakai backoff eksponensial dengan jitter acak (tidak diseed). Jeda tetap akan
        # berfase sama dengan irama probe (sekitar 0,3 detik) dan bisa kelaparan terus-menerus.
        rng = random.Random()
        jeda = 0.03
        try:
            percobaan = 0
            while True:
                percobaan += 1
                hasil_pemegang["hasil"] = pemegang.panggil(
                    "tulis", timeout=90, kunci_operasi="ingest: hermes/default/uji-t08#1-2",
                    perubahan=[perubahan("wiki/sesi/uji-t08-a.md", "# A\n", None)], tambahan_log=[], alasan="uji T8")
                hasil_pemegang["percobaan"] = percobaan
                hasil_pemegang["riwayat"].append((round(time.monotonic() - mulai, 2), hasil_pemegang["hasil"].get("status")))
                if (hasil_pemegang["hasil"].get("status") != "terkunci" or polling_selesai.is_set()
                        or time.monotonic() - mulai > BATAS_ULANG_PEMEGANG):
                    break
                time.sleep(jeda + rng.uniform(0, jeda))
                jeda = min(jeda * 1.6, 0.5)
        except Exception as exc:  # pragma: no cover - dilaporkan di bawah
            hasil_pemegang["galat"] = exc

    t = threading.Thread(target=jalan)
    t.start()

    # Polling maksimal 5 detik sampai kunci terpegang. TAFSIRAN: sinyalnya adalah tulis
    # "probe" dengan hash_lama salah: jawabannya `berubah` (tidak menulis apa pun) selama
    # kunci belum dipegang, dan `terkunci` setelah kunci dipegang.
    probe_kunci = "ingest: claude/-/c-uji-t08-probe#1-2"
    probe = dict(kunci_operasi=probe_kunci, perubahan=[perubahan(PROFIL, "# probe\n", HASH_SALAH)],
                 tambahan_log=[], alasan="uji T8 probe")
    batas = time.monotonic() + 5
    terakhir: Any = None
    garis: list[tuple[float, Any]] = []  # (detik sejak mulai, status probe), untuk pesan diagnostik
    while time.monotonic() < batas:
        terakhir = penulis.panggil("tulis", **probe)
        garis.append((round(time.monotonic() - mulai, 2), terakhir.get("status") if isinstance(terakhir, dict) else terakhir))
        if isinstance(terakhir, dict) and terakhir.get("status") == "terkunci":
            break
        assert isinstance(terakhir, dict) and terakhir.get("status") == "berubah", f"T8 probe: {terakhir!r}"
        time.sleep(0.2)
    polling_selesai.set()
    cek(terakhir, "terkunci",
        f"T8: kunci tidak terpegang dalam 5 detik [probe: {len(garis)}x, {garis[:3]} ... {garis[-2:]}; "
        f"pemegang: percobaan={hasil_pemegang.get('percobaan')}, riwayat={hasil_pemegang.get('riwayat')}, "
        f"hasil={hasil_pemegang.get('hasil')}, galat={hasil_pemegang.get('galat')!r}]")

    hasil = penulis.panggil("tulis", kunci_operasi="ingest: claude/-/c-uji-t08#1-2",
                            perubahan=[perubahan("wiki/sesi/uji-t08-b.md", "# B\n", None)], tambahan_log=[], alasan="uji T8")
    tertahan = t.is_alive()
    t.join(timeout=90)
    cek(hasil, "terkunci", "T8 penulis kedua")
    assert tertahan, "T8: tulis pemegang kunci selesai sebelum penulis kedua mencoba; uji tidak bermakna"
    assert "galat" not in hasil_pemegang, f"T8 pemegang: {hasil_pemegang.get('galat')!r}"
    cek(hasil_pemegang.get("hasil"), "selesai", "T8 pemegang")
    assert not (vault / "wiki/sesi/uji-t08-b.md").exists(), "T8: penulis yang `terkunci` tetap menulis"
    # `terkunci` tidak meninggalkan catatan yang mengunci kunci operasi (kontrak §6, amandemen D.16).
    cek(penulis.panggil("tulis", kunci_operasi="ingest: claude/-/c-uji-t08#1-2",
                        perubahan=[perubahan("wiki/sesi/uji-t08-b.md", "# B\n", None)], tambahan_log=[], alasan="uji T8"),
        "selesai", "T8 coba lagi setelah kunci dilepas")


def test_t09_kegagalan_parsial(server, vault):
    p0, l0 = byte_file(vault, PROFIL), byte_file(vault, LOG_PROFIL)
    p1 = tambah_fakta(p0.decode("utf-8"), "- Fakta T9.").encode("utf-8")
    kunci = "sinkron: claude/-/c-uji-t09/aaaa0009"
    e = entri_log(kunci, "profil")
    permintaan = dict(kunci_operasi=kunci, perubahan=[perubahan(PROFIL, p1.decode("utf-8"), sha_byte(p0))],
                      tambahan_log=[tambahan(LOG_PROFIL, kunci, e)], alasan="uji T9")

    rusak = server(fault="henti_setelah_target_pertama", nama="rusak")
    hasil = panggil_bisa_putus(rusak, "tulis", **permintaan)
    if hasil is not None:
        cek_gagal_dengan_id(hasil, "T9 panggilan pertama")  # amandemen A.3: juga sah
    rusak.tunggu_berhenti()

    profil_berubah = byte_file(vault, PROFIL) != p0
    log_berubah = byte_file(vault, LOG_PROFIL) != l0
    assert profil_berubah != log_berubah, (
        f"T9: harus tepat satu target berubah (profil berubah={profil_berubah}, log berubah={log_berubah})")
    parsial = potret(vault)

    baru = server(nama="baru")
    op_id = cek_gagal_dengan_id(baru.panggil("tulis", **permintaan), "T9 pengulangan")
    # Amandemen A.2: selama belum dipulihkan, setiap tulis dan tambah_log -> `terkunci`, pesan menyebut op_id.
    lain = dict(kunci_operasi="ingest: claude/-/c-uji-t09-lain#1-2",
                perubahan=[perubahan("wiki/sesi/uji-t09-lain.md", "# Lain\n", None)], tambahan_log=[], alasan="uji T9")
    kunci_log = "tangkap: claude/-/c-uji-t09-lain#3-4"
    cek_terkunci_oleh(baru.panggil("tulis", **lain), op_id, "T9 tulis lain sebelum pemulihan")
    cek_terkunci_oleh(baru.panggil("tambah_log", path=LOG_PROFIL, kunci=kunci_log, teks=entri_log(kunci_log, "potongan"),
                                   alasan="uji T9"), op_id, "T9 tambah_log sebelum pemulihan")
    # Amandemen 2 §9: baca dan daftar tetap berjalan normal selama operasi tertunda.
    terbaca = cek(baru.panggil("baca", path=PROFIL), "selesai", "T9 baca saat tertunda")
    assert terbaca.get("isi", "").encode("utf-8") == byte_file(vault, PROFIL), "T9: baca saat tertunda tidak sama dengan disk"
    assert isinstance(baru.panggil("daftar", folder="wiki/profil"), list), "T9: daftar saat tertunda tidak berupa array"
    baru.tutup()
    restart = server(nama="restart")
    cek_terkunci_oleh(restart.panggil("tulis", **lain), op_id, "T9 tulis lain setelah restart")
    restart.tutup()
    assert potret(vault) == parsial, "T9: vault berubah sebelum pemulihan"

    uji_pulihkan_dan_ulang(server, vault, op_id, permintaan,
                           target_baru={PROFIL: p1, LOG_PROFIL: l0 + e.encode("utf-8")},
                           target_lama={PROFIL: p0, LOG_PROFIL: l0}, konteks="T9")
    cek(server(nama="sesudah").panggil("tulis", **lain), "selesai", "T9 tulis lain setelah pemulihan")


def test_t10_jalur_hermes_memakai_helper_yang_sama(vault):
    # Amandemen A.1: `<python> -m claude_obsidian.memori_validasi --periksa`, operasi JSON di stdin,
    # hasil `{lolos, alasan}` di stdout. Interpreter diturunkan dari MEMORI_GUARD_CMD.
    if perintah_python() is None:
        pytest.skip("MEMORI_GUARD_CMD tidak memakai `-m`; interpreter untuk --periksa tidak bisa diturunkan")
    lama = teks_file(vault, LOG_PROFIL)
    h = sha_file(vault, LOG_PROFIL)
    sebelum = potret(vault)

    def periksa(operasi: dict[str, Any], konteks: str) -> dict[str, Any]:
        proses, hasil = jalankan_periksa(vault, operasi)
        assert isinstance(hasil, dict) and isinstance(hasil.get("lolos"), bool), (
            f"{konteks}: keluaran --periksa bukan {{lolos, alasan}} (kode {proses.returncode})\n"
            f"stdout: {proses.stdout.decode('utf-8', 'replace')}\nstderr: {proses.stderr.decode('utf-8', 'replace')}")
        assert isinstance(hasil.get("alasan"), list), f"{konteks}: alasan bukan array: {hasil!r}"
        return hasil

    ubah = periksa(dict(kunci_operasi="ingest: hermes/default/uji-t10#1-2",
                        perubahan=[perubahan(LOG_PROFIL, lama.replace("# Log Profil", "# Log Diubah") + entri_log("id: t10"), h)],
                        tambahan_log=[], alasan="uji T10"), "T10 ubah baris lama")
    assert ubah["lolos"] is False and ubah["alasan"], f"T10: perubahan baris lama di Log lolos: {ubah!r}"

    kontrol = periksa(dict(kunci_operasi="ingest: hermes/default/uji-t10#3-4",
                           perubahan=[perubahan("wiki/sesi/uji-t10.md", "# Uji T10\n", None)],
                           tambahan_log=[tambahan(LOG_PROFIL, "ingest: hermes/default/uji-t10#3-4")],
                           alasan="uji T10"), "T10 kontrol")
    assert kontrol["lolos"] is True, f"T10 kontrol: operasi sah ditolak: {kontrol!r}"
    assert potret(vault) == sebelum, "T10: --periksa mengubah vault"


def test_t11_respons_hilang_pengulangan_sudah_ada(server, vault):
    klien = server()
    kunci = "ingest: claude/-/c-uji-t11#1-9"
    catatan = "wiki/sesi/uji-t11.md"
    permintaan = dict(kunci_operasi=kunci,
                      perubahan=[perubahan(catatan, "# Uji T11\n\n- Isi pertama.\n", None)],
                      tambahan_log=[tambahan(LOG_PROFIL, kunci)], alasan="uji T11")
    cek(klien.panggil("tulis", **permintaan), "selesai", "T11 pertama")
    sesudah_pertama = potret(vault)

    cek(klien.panggil("tulis", **permintaan), "sudah_ada", "T11 pengulangan sama persis")
    assert potret(vault) == sesudah_pertama, "T11: pengulangan mengubah vault"
    assert hitung(byte_file(vault, LOG_PROFIL), kunci) == 1, "T11: entri Log ganda"

    beda = dict(permintaan, perubahan=[perubahan(catatan, "# Uji T11\n\n- Isi berbeda.\n", None)])
    cek(klien.panggil("tulis", **beda), "ditolak", "T11 kunci sama isi berbeda")
    assert potret(vault) == sesudah_pertama, "T11: permintaan yang ditolak mengubah vault"


def test_t12_rangkaian_log_kunci_di_log_pertama_dikenali(server, vault):
    kunci = "ingest: hermes/default/uji-t12#1-5"
    (vault / "sesi-log/uji-topik-log.md").write_bytes(
        ("---\ntitle: Log Uji Topik\ntype: sesi-log\ncreated: 2026-11-16\ntags: [sesi-log]\n---\n\n"
         "# Log Uji Topik\n" + entri_log(kunci)).encode("utf-8"))
    (vault / "sesi-log/uji-topik-log-2.md").write_bytes(
        b"---\ntitle: Log Uji Topik (2)\ntype: sesi-log\ncreated: 2026-11-16\ntags: [sesi-log]\n---\n\n"
        b"# Log Uji Topik (2)\n")
    klien = server()
    sebelum = potret(vault)
    # Kunci ada di -log.md tanpa catatan operasi -> `ditolak` (spesifikasi langkah 2, amandemen C.11).
    cek(klien.panggil("tambah_log", path="sesi-log/uji-topik-log-2.md", kunci=kunci,
                      teks=entri_log(kunci), alasan="uji T12"), "ditolak", "T12 lewat tambah_log")
    assert potret(vault) == sebelum, "T12: entri ditambahkan lagi"
    cek(klien.panggil("tulis", kunci_operasi=kunci, perubahan=[],
                      tambahan_log=[tambahan("sesi-log/uji-topik-log-2.md", kunci)], alasan="uji T12"),
        "ditolak", "T12 lewat tulis")
    assert potret(vault) == sebelum, "T12: entri ditambahkan lagi lewat tulis"
    # Kontrol: kunci baru ke -log-2.md diterima.
    cek(klien.panggil("tambah_log", path="sesi-log/uji-topik-log-2.md", kunci="ingest: hermes/default/uji-t12#6-9",
                      teks=entri_log("ingest: hermes/default/uji-t12#6-9"), alasan="uji T12"), "selesai", "T12 kontrol")


def test_t13_beberapa_entri_ke_log_yang_sama(server, vault):
    klien = server()
    l0 = byte_file(vault, LOG_PROFIL)
    kunci = "ingest: claude/-/c-uji-t13#1-20"
    entri = [
        tambahan(LOG_PROFIL, kunci, entri_log(kunci, "akhir-sesi")),
        tambahan(LOG_PROFIL, "id: uji-t13-perubahan-1", entri_log("id: uji-t13-perubahan-1", "perubahan", "- Diganti: satu.")),
        tambahan(LOG_PROFIL, "id: uji-t13-perubahan-2", entri_log("id: uji-t13-perubahan-2", "perubahan", "- Diganti: dua.")),
    ]
    p0 = teks_file(vault, PROFIL)
    hasil = klien.panggil("tulis", kunci_operasi=kunci,
                          perubahan=[perubahan(PROFIL, tambah_fakta(p0, "- Fakta T13."), sha_file(vault, PROFIL))],
                          tambahan_log=entri, alasan="uji T13")
    cek(hasil, "selesai", "T13")
    harapan = l0 + "".join(e["teks"] for e in entri).encode("utf-8")
    assert byte_file(vault, LOG_PROFIL) == harapan, "T13: Log bukan isi lama + entri sesuai urutan kiriman"
    # Amandemen B.8: paths unik, urutan kemunculan pertama di permintaan.
    assert norm_paths(hasil) == [PROFIL, LOG_PROFIL], f"T13: paths {hasil.get('paths')!r}"


def test_t14_kunci_sinkron_profil(server, vault):
    klien = server()

    def kunci_sinkron(bahan: str) -> str:
        return f"sinkron: claude/-/c-20261116-1000-uji4/{hashlib.sha256(bahan.encode('utf-8')).hexdigest()[:8]}"

    def permintaan(bahan: str) -> dict[str, Any]:
        kunci = kunci_sinkron(bahan)
        return dict(kunci_operasi=kunci,
                    perubahan=[perubahan(PROFIL, tambah_fakta(teks_file(vault, PROFIL), bahan), sha_file(vault, PROFIL))],
                    tambahan_log=[tambahan(LOG_PROFIL, kunci, entri_log(kunci, "profil"))], alasan="uji T14")

    bahan1 = "- Fakta sinkron pertama. · dinyatakan ? · dicatat 2026-11-16 · claude · - · c-20261116-1000-uji4"
    bahan2 = "- Fakta sinkron kedua. · dinyatakan ? · dicatat 2026-11-16 · claude · - · c-20261116-1000-uji4"
    r1 = permintaan(bahan1)
    cek(klien.panggil("tulis", **r1), "selesai", "T14 sinkron pertama")
    r2 = permintaan(bahan2)
    assert r1["kunci_operasi"] != r2["kunci_operasi"]
    cek(klien.panggil("tulis", **r2), "selesai", "T14 sinkron kedua (bahan berbeda)")
    setelah_dua = potret(vault)
    log = byte_file(vault, LOG_PROFIL)
    assert hitung(log, r1["kunci_operasi"]) == 1 and hitung(log, r2["kunci_operasi"]) == 1

    cek(klien.panggil("tulis", **r1), "sudah_ada", "T14 pengulangan sinkron pertama")
    assert potret(vault) == setelah_dua, "T14: pengulangan mengubah vault"


# -- T15–T16: tambahan dari kontrak --------------------------------------------------

def test_t15_konflik_tidak_mengunci_kunci(server, vault):
    klien = server()
    kunci = "ingest: claude/-/c-uji-t15#1-4"
    p0 = teks_file(vault, PROFIL)
    hasil = cek(klien.panggil("tulis", kunci_operasi=kunci,
                              perubahan=[perubahan(PROFIL, tambah_fakta(p0, "- Fakta T15 versi usang."), HASH_SALAH)],
                              tambahan_log=[tambahan(LOG_PROFIL, kunci)], alasan="uji T15"), "berubah", "T15 hash usang")
    assert hasil.get("hash_terkini") == {PROFIL: sha_file(vault, PROFIL)}, f"T15: {hasil!r}"
    terkini = cek(klien.panggil("baca", path=PROFIL), "selesai", "T15 baca ulang")
    cek(klien.panggil("tulis", kunci_operasi=kunci,
                      perubahan=[perubahan(PROFIL, tambah_fakta(terkini["isi"], "- Fakta T15 disusun ulang."),
                                           terkini["sha256"])],
                      tambahan_log=[tambahan(LOG_PROFIL, kunci)], alasan="uji T15 disusun ulang"),
        "selesai", "T15 susun ulang dengan kunci sama")
    assert "Fakta T15 disusun ulang." in teks_file(vault, PROFIL)


def test_t16a_dua_proses_kunci_sama_bersamaan(server, vault):
    a, b = server(nama="a"), server(nama="b")
    kunci = "ingest: claude/-/c-uji-t16a#1-3"
    catatan = "wiki/sesi/uji-t16a.md"
    isi = "# Uji T16a\n"
    e = entri_log(kunci)
    permintaan = dict(kunci_operasi=kunci, perubahan=[perubahan(catatan, isi, None)],
                      tambahan_log=[tambahan(LOG_PROFIL, kunci, e)], alasan="uji T16a")
    l0 = byte_file(vault, LOG_PROFIL)
    serentak = threading.Barrier(2)
    hasil: dict[str, Any] = {}

    def jalan(nama: str, klien: KlienMcp) -> None:
        serentak.wait()
        try:
            hasil[nama] = klien.panggil("tulis", **permintaan)
        except Exception as exc:  # pragma: no cover
            hasil[nama] = exc

    utas = [threading.Thread(target=jalan, args=(n, k)) for n, k in (("a", a), ("b", b))]
    for t in utas:
        t.start()
    for t in utas:
        t.join(timeout=120)
    status = sorted(h.get("status") if isinstance(h, dict) else repr(h) for h in hasil.values())
    assert status.count("selesai") == 1, f"T16a: harus tepat satu `selesai`: {hasil!r}"
    lain = [s for s in status if s != "selesai"]
    assert lain and lain[0] in {"sudah_ada", "terkunci", "berubah"}, f"T16a: hasil proses lain {hasil!r}"
    assert byte_file(vault, catatan) == isi.encode("utf-8")
    assert byte_file(vault, LOG_PROFIL) == l0 + e.encode("utf-8"), "T16a: Log tertulis ganda atau salah"


def test_t16b_henti_sebelum_catat_hasil_lalu_sudah_ada(server, vault):
    kunci = "ingest: claude/-/c-uji-t16b#1-3"
    catatan = "wiki/sesi/uji-t16b.md"
    isi = "# Uji T16b\n"
    e = entri_log(kunci)
    l0 = byte_file(vault, LOG_PROFIL)
    permintaan = dict(kunci_operasi=kunci, perubahan=[perubahan(catatan, isi, None)],
                      tambahan_log=[tambahan(LOG_PROFIL, kunci, e)], alasan="uji T16b")
    rusak = server(fault="henti_sebelum_catat_hasil", nama="rusak")
    panggil_bisa_putus(rusak, "tulis", **permintaan)
    rusak.tunggu_berhenti()
    assert byte_file(vault, catatan) == isi.encode("utf-8"), "T16b: catatan belum tertulis sebelum proses berhenti"
    assert byte_file(vault, LOG_PROFIL) == l0 + e.encode("utf-8"), "T16b: Log belum tertulis sebelum proses berhenti"
    sesudah_henti = potret(vault)

    baru = server(nama="baru")
    cek(baru.panggil("tulis", **permintaan), "sudah_ada", "T16b pengulangan setelah restart")
    assert potret(vault) == sesudah_henti, "T16b: pengulangan mengubah vault"
    assert hitung(byte_file(vault, LOG_PROFIL), kunci) == 1
    # Rekonsiliasi `selesai` tidak meninggalkan kunci tulis vault.
    cek(baru.panggil("tulis", kunci_operasi="ingest: claude/-/c-uji-t16b-lain#1-2",
                     perubahan=[perubahan("wiki/sesi/uji-t16b-lain.md", "# Lain\n", None)], tambahan_log=[],
                     alasan="uji T16b"), "selesai", "T16b tulis lain setelah rekonsiliasi")


def test_t16c_henti_setelah_target_pertama_lalu_gagal_dan_pulihkan(server, vault):
    kunci = "ingest: claude/-/c-uji-t16c#1-3"
    catatan = "wiki/sesi/uji-t16c.md"
    isi = "# Uji T16c\n"
    e = entri_log(kunci)
    l0 = byte_file(vault, LOG_PROFIL)
    permintaan = dict(kunci_operasi=kunci, perubahan=[perubahan(catatan, isi, None)],
                      tambahan_log=[tambahan(LOG_PROFIL, kunci, e)], alasan="uji T16c")
    rusak = server(fault="henti_setelah_target_pertama", nama="rusak")
    panggil_bisa_putus(rusak, "tulis", **permintaan)
    rusak.tunggu_berhenti()
    catatan_ada = (vault / catatan).exists()
    log_berubah = byte_file(vault, LOG_PROFIL) != l0
    assert catatan_ada != log_berubah, f"T16c: harus tepat satu target berubah (catatan={catatan_ada}, log={log_berubah})"

    baru = server(nama="baru")
    op_id = cek_gagal_dengan_id(baru.panggil("tulis", **permintaan), "T16c pengulangan setelah restart")
    baru.tutup()
    # Amandemen A.5: kedua kemungkinan hasil pemulihan diperiksa beserta pengulangannya.
    uji_pulihkan_dan_ulang(server, vault, op_id, permintaan,
                           target_baru={catatan: isi.encode("utf-8"), LOG_PROFIL: l0 + e.encode("utf-8")},
                           target_lama={catatan: None, LOG_PROFIL: l0}, konteks="T16c")


def test_t16d_henti_setelah_catat_berjalan_lalu_selesai(server, vault):
    # Amandemen 2 §8: catatan `berjalan` tanpa perubahan target direkonsiliasi jadi
    # `dibatalkan`, kunci operasinya dilepas, sehingga pengulangan -> `selesai`.
    kunci = "ingest: claude/-/c-uji-t16d#1-3"
    catatan = "wiki/sesi/uji-t16d.md"
    isi = "# Uji T16d\n"
    e = entri_log(kunci)
    l0 = byte_file(vault, LOG_PROFIL)
    permintaan = dict(kunci_operasi=kunci, perubahan=[perubahan(catatan, isi, None)],
                      tambahan_log=[tambahan(LOG_PROFIL, kunci, e)], alasan="uji T16d")
    sebelum = potret(vault)
    rusak = server(fault="henti_setelah_catat_berjalan", nama="rusak")
    hasil = panggil_bisa_putus(rusak, "tulis", **permintaan)
    assert hasil is None, f"T16d: server menjawab padahal fault menghentikan proses: {hasil!r}"
    rusak.tunggu_berhenti()
    assert potret(vault) == sebelum, "T16d: ada target berubah padahal proses berhenti sebelum execute"

    baru = server(nama="baru")
    cek(baru.panggil("tulis", **permintaan), "selesai", "T16d pengulangan setelah restart")
    assert byte_file(vault, catatan) == isi.encode("utf-8")
    assert byte_file(vault, LOG_PROFIL) == l0 + e.encode("utf-8"), "T16d: Log tidak sama dengan isi lama + entri"


# -- T17: validasi tambahan (amandemen E.18) ----------------------------------------------

def test_t17a_kunci_tidak_ada_di_teks_ditolak(server, vault):
    klien = server()
    sebelum = potret(vault)
    teks = entri_log("tangkap: claude/-/c-uji-t17a#lain", "potongan")
    cek(klien.panggil("tambah_log", path=LOG_PROFIL, kunci="tangkap: claude/-/c-uji-t17a#1-2", teks=teks,
                      alasan="uji T17a"), "ditolak", "T17a tambah_log")
    cek(klien.panggil("tulis", kunci_operasi="ingest: claude/-/c-uji-t17a#1-2", perubahan=[],
                      tambahan_log=[{"path": LOG_PROFIL, "kunci": "ingest: claude/-/c-uji-t17a#1-2", "teks": teks}],
                      alasan="uji T17a"), "ditolak", "T17a tulis")
    assert potret(vault) == sebelum


def test_t17b_lebih_dari_sepuluh_item_ditolak(server, vault):
    klien = server()
    sebelum = potret(vault)
    sebelas_perubahan = [perubahan(f"wiki/sesi/uji-t17b-{i:02d}.md", f"# {i}\n", None) for i in range(11)]
    cek(klien.panggil("tulis", kunci_operasi="ingest: claude/-/c-uji-t17b-p#1-2", perubahan=sebelas_perubahan,
                      tambahan_log=[], alasan="uji T17b"), "ditolak", "T17b 11 perubahan")
    sebelas_log = [tambahan(LOG_PROFIL, f"id: uji-t17b-{i:02d}") for i in range(11)]
    cek(klien.panggil("tulis", kunci_operasi="ingest: claude/-/c-uji-t17b-l#1-2", perubahan=[],
                      tambahan_log=sebelas_log, alasan="uji T17b"), "ditolak", "T17b 11 tambahan_log")
    assert potret(vault) == sebelum
    # Kontrol: tepat 10 item di masing-masing diterima.
    cek(klien.panggil("tulis", kunci_operasi="ingest: claude/-/c-uji-t17b-ok#1-2", perubahan=sebelas_perubahan[:10],
                      tambahan_log=sebelas_log[:10], alasan="uji T17b"), "selesai", "T17b kontrol 10 + 10")


def test_t17c_perubahan_dan_tambahan_log_kosong_ditolak(server, vault):
    sebelum = potret(vault)
    cek(server().panggil("tulis", kunci_operasi="ingest: claude/-/c-uji-t17c#1-2", perubahan=[], tambahan_log=[],
                         alasan="uji T17c"), "ditolak", "T17c")
    assert potret(vault) == sebelum


def test_t17d_log_melewati_batas_ditolak_dengan_pesan_lanjutan(server, vault, batas_byte):
    # Log disiapkan 50 byte di bawah batas; entri 100+ byte membuatnya melewati batas.
    rel = "sesi-log/uji-besar-log.md"
    kepala = b"---\ntitle: Log Uji Besar\ntype: sesi-log\ncreated: 2026-11-16\ntags: [sesi-log]\n---\n\n# Log Uji Besar\n\n"
    isi = kepala + b"x" * (batas_byte - 50 - len(kepala) - 1) + b"\n"
    assert len(isi) == batas_byte - 50
    (vault / rel).write_bytes(isi)
    # Amandemen 2 §4: server dijalankan dengan `--batas-byte`; batas berlaku untuk ukuran akhir file.
    klien = server(batas_byte=batas_byte)
    sebelum = potret(vault)
    kunci = "tangkap: claude/-/c-uji-t17d#1-2"
    teks = entri_log(kunci, "potongan", "- " + "y" * 120)
    hasil = cek(klien.panggil("tambah_log", path=rel, kunci=kunci, teks=teks, alasan="uji T17d"),
                "ditolak", "T17d tambah_log")
    # Keputusan Example User (Fase B): pesan menyebut path relatif vault dari file lanjutan berikutnya
    # yang belum ada dalam rangkaian.
    assert "sesi-log/uji-besar-log-2.md" in str(hasil.get("pesan", "")), f"T17d: pesan tidak menyebut file lanjutan: {hasil!r}"
    hasil = cek(klien.panggil("tulis", kunci_operasi=kunci, perubahan=[],
                              tambahan_log=[tambahan(rel, kunci, teks)], alasan="uji T17d"), "ditolak", "T17d tulis")
    assert "sesi-log/uji-besar-log-2.md" in str(hasil.get("pesan", "")), f"T17d tulis: pesan tidak menyebut file lanjutan: {hasil!r}"
    # Batas yang sama berlaku untuk catatan baru.
    cek(klien.panggil("tulis", kunci_operasi="ingest: claude/-/c-uji-t17d-catatan#1-2",
                      perubahan=[perubahan("wiki/sesi/uji-t17d.md", "# Besar\n" + "z" * batas_byte, None)],
                      tambahan_log=[], alasan="uji T17d"), "ditolak", "T17d catatan di atas batas")
    assert potret(vault) == sebelum

    # Ukuran persis N byte diterima; hanya di atas N yang ditolak (keputusan Example User).
    kunci_pas = "tangkap: claude/-/c-uji-t17d#3-4"
    awal_pas = f"\n{kunci_pas}\n- "
    teks_pas = awal_pas + "w" * (50 - len(awal_pas.encode("utf-8")) - 1) + "\n"
    assert len(teks_pas.encode("utf-8")) == 50
    cek(klien.panggil("tambah_log", path=rel, kunci=kunci_pas, teks=teks_pas, alasan="uji T17d"),
        "selesai", "T17d Log tepat N byte")
    assert byte_file(vault, rel) == isi + teks_pas.encode("utf-8")
    assert (vault / rel).stat().st_size == batas_byte
    catatan_pas = "# Pas\n" + "z" * (batas_byte - len("# Pas\n"))
    assert len(catatan_pas.encode("utf-8")) == batas_byte
    cek(klien.panggil("tulis", kunci_operasi="ingest: claude/-/c-uji-t17d-pas#1-2",
                      perubahan=[perubahan("wiki/sesi/uji-t17d-pas.md", catatan_pas, None)],
                      tambahan_log=[], alasan="uji T17d"), "selesai", "T17d catatan tepat N byte")
    assert (vault / "wiki/sesi/uji-t17d-pas.md").stat().st_size == batas_byte

    # Jika `<topik>-log-2.md` sudah ada, file lanjutan berikutnya adalah `<topik>-log-3.md`.
    # File -log-2 disiapkan langsung di vault sementara (seperti yang akan dibuat Hermes), 50 byte di bawah batas.
    rel2 = "sesi-log/uji-besar-log-2.md"
    kepala2 = (b"---\ntitle: Log Uji Besar (2)\ntype: sesi-log\ncreated: 2026-11-16\ntags: [sesi-log]\n---\n\n"
               b"# Log Uji Besar (2)\n\n")
    isi2 = kepala2 + b"x" * (batas_byte - 50 - len(kepala2) - 1) + b"\n"
    (vault / rel2).write_bytes(isi2)
    sebelum = potret(vault)
    for target in (rel2, rel):
        kunci3 = f"tangkap: claude/-/c-uji-t17d-log3-{target.rsplit('/', 1)[-1]}#5-6"
        hasil = cek(klien.panggil("tambah_log", path=target, kunci=kunci3,
                                  teks=entri_log(kunci3, "potongan", "- " + "y" * 120), alasan="uji T17d"),
                    "ditolak", f"T17d -log-2 sudah ada, tambah ke {target}")
        pesan = str(hasil.get("pesan", ""))
        assert "sesi-log/uji-besar-log-3.md" in pesan, f"T17d ({target}): pesan tidak menyebut -log-3: {hasil!r}"
        assert "uji-besar-log-2.md" not in pesan, f"T17d ({target}): pesan masih menyebut -log-2 yang sudah ada: {hasil!r}"
    assert potret(vault) == sebelum


def test_t17e_baca_di_atas_batas_ditolak_tidak_dipotong(server, vault, batas_byte):
    rel = "wiki/sesi/uji-besar.md"
    (vault / rel).write_bytes(b"# Besar\n\n" + b"z" * (batas_byte + 1 - 9))
    assert (vault / rel).stat().st_size == batas_byte + 1
    hasil = server(batas_byte=batas_byte).panggil("baca", path=rel)
    # Amandemen 2 §5: {status: "ditolak", path, pesan}, tanpa `isi` dan `sha256`.
    cek(hasil, "ditolak", "T17e")
    assert hasil.get("path") == rel and hasil.get("pesan"), f"T17e: {hasil!r}"
    assert "isi" not in hasil and "sha256" not in hasil, f"T17e: isi/sha256 tetap dikirim: {sorted(hasil)}"
