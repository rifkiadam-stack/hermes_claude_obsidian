"""Fixture bersama untuk uji penerimaan `memori-guard` (T0–T23).

- Tanpa `MEMORI_GUARD_CMD`, semua tes di folder ini di-skip.
- Setiap tes memakai vault sementara sendiri, disalin dari kerangka v3.3.
- Fase E: `vault_pengetahuan` menambah halaman pengetahuan contoh; `bangun_indeks`
  dan `vault_berindeks` memakai perintah Hermes dari `MEMORI_GUARD_BUILD_INDEX_CMD`
  dan di-skip jika variabel itu kosong.
- Pengaman: sesi pytest langsung berhenti jika vault atau kerangka berada di
  bawah `Z:/Protected Test Root`.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import tempfile
from pathlib import Path
from typing import Callable, Iterator

import pytest

from mcp_klien import (ENV_BANGUN_INDEKS, KODE_BANGUN_BERHASIL, KlienMcp, di_bawah_my_drive,
                       folder_scratch_izin, jalankan_bangun_indeks, perintah_bangun_indeks, perintah_server)

FOLDER_INI = Path(__file__).resolve().parent
KERANGKA_BAWAAN = FOLDER_INI / "fixtures" / "kerangka-vault"


def _berhenti_jika_my_drive(path: os.PathLike[str] | str, peran: str) -> None:
    if di_bawah_my_drive(path):
        pytest.exit(
            f"DIHENTIKAN: {peran} berada di bawah Z:/Protected Test Root ({path}). "
            "Uji memori-guard tidak boleh menyentuh vault aktif.",
            returncode=3,
        )


def pytest_configure(config: pytest.Config) -> None:
    try:
        folder_scratch_izin()
    except ValueError as exc:
        pytest.exit(f"DIHENTIKAN: {exc}", returncode=3)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo):
    outcome = yield
    setattr(item, "rep_" + call.when, outcome.get_result())


def _gagal(node: pytest.Item) -> bool:
    return any(getattr(node, f"rep_{tahap}", None) is not None and getattr(node, f"rep_{tahap}").failed
               for tahap in ("setup", "call"))


def _basis_sementara() -> str | None:
    """Folder induk vault sementara: scratch di G: jika diizinkan eksplisit, selain itu temp sistem."""
    if folder_scratch_izin() is None:
        return None
    basis = Path("Z:/Protected Test Root/_uji-memori-guard")
    basis.mkdir(exist_ok=True)  # hanya folder ini; induknya `Z:/Protected Test Root` harus sudah ada
    return str(basis)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if perintah_server() is not None:
        return
    lewati = pytest.mark.skip(
        reason="MEMORI_GUARD_CMD tidak diisi; isi dengan perintah server memori-guard "
               "(tanpa --vault) untuk menjalankan uji penerimaan."
    )
    for item in items:
        if FOLDER_INI in Path(str(item.fspath)).resolve().parents:
            item.add_marker(lewati)


@pytest.fixture(scope="session")
def kerangka() -> Path:
    raw = os.environ.get("MEMORI_GUARD_SKELETON", "").strip()
    path = Path(raw) if raw else KERANGKA_BAWAAN
    _berhenti_jika_my_drive(path, "MEMORI_GUARD_SKELETON")
    if not (path / "_konvensi-memori.md").is_file():
        pytest.fail(f"kerangka vault tidak valid (tidak ada _konvensi-memori.md): {path}")
    return path


def _hapus_pohon(path: Path) -> None:
    """Hapus direktori sementara; junction dilepas dulu tanpa menyentuh targetnya."""
    if not path.exists():
        return
    assert path.name.startswith("memori-guard-uji-"), f"menolak menghapus folder di luar pola uji: {path}"
    for akar, dirs, _files in os.walk(path, topdown=True):
        for nama in list(dirs):
            p = Path(akar) / nama
            if p.is_symlink() or (hasattr(p, "is_junction") and p.is_junction()) or _junction(p):
                os.rmdir(p) if not p.is_symlink() else p.unlink()
                dirs.remove(nama)

    def _onerror(func, p, _exc):  # pragma: no cover - hanya pembersihan
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except OSError:
            pass

    shutil.rmtree(path, onerror=_onerror)


def _junction(p: Path) -> bool:
    try:
        st = os.lstat(p)
    except OSError:
        return False
    return bool(getattr(st, "st_file_attributes", 0) & 0x400)  # FILE_ATTRIBUTE_REPARSE_POINT


@pytest.fixture
def ruang_kerja(request: pytest.FixtureRequest) -> Iterator[Path]:
    """Direktori sementara: berisi `vault/` dan tempat log stderr server.

    Jika tes gagal, direktori dan isinya (vault, stderr server) **dipertahankan** dan
    path-nya dicetak; direktori hanya dihapus saat tes lulus.
    """
    basis = _basis_sementara()
    if basis is None:
        _berhenti_jika_my_drive(tempfile.gettempdir(), "direktori temp sistem")
    akar = Path(tempfile.mkdtemp(prefix="memori-guard-uji-", dir=basis))
    _berhenti_jika_my_drive(akar, "direktori uji sementara")
    try:
        yield akar
    finally:
        if _gagal(request.node):
            print(f"\nDIPERTAHANKAN (tes gagal): {akar}")
        else:
            _hapus_pohon(akar)


DASAR_BAWAAN = FOLDER_INI / "fixtures" / "dasar-vault"


@pytest.fixture
def vault(kerangka: Path, ruang_kerja: Path) -> Path:
    """Vault sementara = `dasar-vault/` (file minimum guard, jika ada) + kerangka v3.3."""
    tujuan = ruang_kerja / "vault"
    _berhenti_jika_my_drive(tujuan, "vault sementara")
    if DASAR_BAWAAN.is_dir():
        shutil.copytree(DASAR_BAWAAN, tujuan)
    shutil.copytree(kerangka, tujuan, dirs_exist_ok=True)
    return tujuan


PENGETAHUAN_BAWAAN = FOLDER_INI / "fixtures" / "pengetahuan-vault"


@pytest.fixture
def vault_pengetahuan(vault: Path) -> Path:
    """Vault sementara + halaman pengetahuan contoh di bawah `wiki/` (Fase E, amandemen 3)."""
    shutil.copytree(PENGETAHUAN_BAWAAN, vault, dirs_exist_ok=True)
    return vault


@pytest.fixture
def bangun_indeks() -> Callable[[Path], None]:
    """Pembangun indeks BM25 dari Hermes; tes di-skip jika perintahnya belum diisi."""
    if perintah_bangun_indeks() is None:
        pytest.skip(f"{ENV_BANGUN_INDEKS} tidak diisi; isi dengan perintah Hermes untuk membangun indeks BM25 "
                    "sebuah vault (array JSON; token {vault} diganti path vault sementara, amandemen 4 §6).")

    def bangun(path_vault: Path) -> None:
        _berhenti_jika_my_drive(path_vault, "vault yang akan diindeks")
        proses = jalankan_bangun_indeks(path_vault)
        if proses.returncode not in KODE_BANGUN_BERHASIL:  # 0 diperbarui, 2 sudah sinkron; 1 gagal
            pytest.fail(f"membangun indeks gagal (kode {proses.returncode})\n"
                        f"stdout: {proses.stdout.decode('utf-8', 'replace')[-3000:]}\n"
                        f"stderr: {proses.stderr.decode('utf-8', 'replace')[-3000:]}")

    return bangun


@pytest.fixture
def vault_berindeks(vault_pengetahuan: Path, bangun_indeks: Callable[[Path], None]) -> Path:
    bangun_indeks(vault_pengetahuan)
    return vault_pengetahuan


BATAS_BYTE_UJI = 4096


@pytest.fixture
def batas_byte() -> int:
    """Nilai `--batas-byte` untuk server T17d/e (amandemen 2 §4).

    Diambil dari `MEMORI_GUARD_BATAS_BYTE`; jika kosong, pakai 4096 supaya tes tidak
    perlu menulis file berukuran megabyte.
    """
    raw = os.environ.get("MEMORI_GUARD_BATAS_BYTE", "").strip()
    if not raw:
        return BATAS_BYTE_UJI
    try:
        nilai = int(raw)
    except ValueError:
        pytest.fail(f"MEMORI_GUARD_BATAS_BYTE bukan bilangan bulat: {raw!r}")
    if nilai <= 0:
        pytest.fail(f"MEMORI_GUARD_BATAS_BYTE harus positif: {nilai}")
    return nilai


@pytest.fixture
def server(request: pytest.FixtureRequest, vault: Path, ruang_kerja: Path) -> Iterator[Callable[..., KlienMcp]]:
    """Pabrik proses server. `server()` normal; `server(fault="...")` mode uji."""
    dibuat: list[KlienMcp] = []

    def buat(fault: str | None = None, nama: str = "server", batas_byte: int | None = None) -> KlienMcp:
        extra = {"MEMORI_GUARD_TEST": "1", "MEMORI_GUARD_FAULT": fault} if fault else None
        argumen = ["--batas-byte", str(batas_byte)] if batas_byte is not None else None
        klien = KlienMcp(vault, env_extra=extra, log_dir=ruang_kerja, nama=f"{nama}{len(dibuat)}",
                         argumen_tambahan=argumen)
        dibuat.append(klien)
        return klien

    try:
        yield buat
    finally:
        for klien in dibuat:
            try:
                klien.__exit__(None, None, None)
            except Exception:
                pass
            if _gagal(request.node):
                print(f"\n--- stderr {klien.nama} ({klien.stderr_path}) ---\n{klien.stderr()[-6000:] or '(kosong)'}")


# -- utilitas yang dipakai tes ------------------------------------------------

def sha_byte(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def sha_file(vault: Path, rel: str) -> str | None:
    p = vault / rel
    return sha_byte(p.read_bytes()) if p.is_file() else None


def byte_file(vault: Path, rel: str) -> bytes | None:
    p = vault / rel
    return p.read_bytes() if p.is_file() else None


def potret(vault: Path) -> dict[str, str]:
    """Hash semua file pengguna yang relevan (bukan runtime/catatan operasi)."""
    hasil: dict[str, str] = {}
    akar_dipantau = [vault / "wiki", vault / "sesi-log"]
    for p in vault.glob("*.md"):
        hasil[p.name] = sha_byte(p.read_bytes())
    for akar in akar_dipantau:
        if not akar.exists():
            continue
        for p in akar.rglob("*"):
            if p.is_file():
                hasil[p.relative_to(vault).as_posix()] = sha_byte(p.read_bytes())
    return hasil


def potret_penuh(vault: Path) -> dict[str, str]:
    """Hash semua file di vault, termasuk folder bertitik dan berkas indeks/runtime."""
    return {p.relative_to(vault).as_posix(): sha_byte(p.read_bytes()) for p in vault.rglob("*") if p.is_file()}
