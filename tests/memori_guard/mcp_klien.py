"""Klien MCP stdio minimal dan sinkron untuk menguji `memori-guard` sebagai kotak hitam.

Hanya klien: modul ini tidak meniru perilaku server apa pun. Server dijalankan
dari perintah di variabel `MEMORI_GUARD_CMD`, ditambah `--vault <path>`.

Transport MCP stdio: JSON-RPC 2.0, satu pesan per baris (UTF-8).
"""

from __future__ import annotations

import json
import os
import queue
import re
import shlex
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

PROTOCOL_VERSION = "2025-06-18"
DEFAULT_TIMEOUT = float(os.environ.get("MEMORI_GUARD_TIMEOUT", "60"))


class ResponsHilang(RuntimeError):
    """Server berhenti atau tidak menjawab sebelum respons diterima."""


class GalatMcp(RuntimeError):
    """Server menjawab dengan galat JSON-RPC."""

    def __init__(self, error: dict[str, Any]):
        super().__init__(f"MCP error {error.get('code')}: {error.get('message')}")
        self.error = error


def perintah_server() -> list[str] | None:
    """Urai `MEMORI_GUARD_CMD`. Mengembalikan None jika tidak diisi.

    Bentuk yang diterima:
    - array JSON, misalnya `["C:/py/python.exe", "-m", "claude_obsidian.memori_guard_mcp"]`;
    - string perintah biasa; token boleh diapit tanda kutip ganda. Gunakan `/`
      di path Windows.
    """
    return _urai_perintah("MEMORI_GUARD_CMD")


def _urai_perintah(nama_env: str) -> list[str] | None:
    raw = os.environ.get(nama_env, "").strip()
    if not raw:
        return None
    if raw.startswith("["):
        cmd = json.loads(raw)
        if not isinstance(cmd, list) or not all(isinstance(x, str) for x in cmd) or not cmd:
            raise ValueError(f"{nama_env} berbentuk JSON harus array string tidak kosong")
        return cmd
    tokens = shlex.split(raw, posix=False)
    return [t[1:-1] if len(t) >= 2 and t[0] == t[-1] == '"' else t for t in tokens]


class VaultAktifTerdeteksi(RuntimeError):
    """Path yang akan dipakai berada di bawah `Z:/Protected Test Root`."""


SCRATCH_IZIN = "z:/protected test root/_uji-memori-guard"
ENV_IZIN_SCRATCH = "MEMORI_GUARD_IZINKAN_SCRATCH"


def _norm(p: str) -> str:
    n = p.replace("\\", "/").lower().rstrip("/")
    return n[4:] if n.startswith("//?/") else n


def folder_scratch_izin() -> str | None:
    """Folder scratch di `Z:/Protected Test Root` yang diizinkan secara eksplisit lewat lingkungan.

    Hanya satu nilai yang diterima: persis `Z:/Protected Test Root/_uji-memori-guard` (huruf
    besar-kecil dan arah garis miring bebas). Nilai lain dianggap salah konfigurasi.
    """
    raw = os.environ.get(ENV_IZIN_SCRATCH, "").strip()
    if not raw:
        return None
    if _norm(os.path.normpath(raw)) != SCRATCH_IZIN:
        raise ValueError(f"{ENV_IZIN_SCRATCH} hanya boleh berisi Z:/Protected Test Root/_uji-memori-guard, bukan {raw!r}")
    return SCRATCH_IZIN


def di_bawah_my_drive(path: str | os.PathLike[str]) -> bool:
    """True jika `path` (atau hasil resolusinya) di bawah Z:/Protected Test Root di luar scratch yang diizinkan.

    Setiap bentuk path (apa adanya dan hasil realpath, sehingga junction dan `..` terdeteksi)
    harus berada di dalam scratch agar lolos; satu saja di luar sudah ditolak.
    """
    izin = folder_scratch_izin()
    kandidat = {os.path.normpath(str(path))}
    try:
        kandidat.add(os.path.realpath(str(path)))
    except OSError:
        pass
    for p in kandidat:
        norm = _norm(p)
        if not (norm == "z:/protected test root" or norm.startswith("z:/protected test root/")):
            continue
        if izin and norm.startswith(izin + "/"):
            continue
        return True
    return False


def pastikan_bukan_vault_aktif(path: str | os.PathLike[str]) -> None:
    if di_bawah_my_drive(path):
        raise VaultAktifTerdeteksi(f"path di bawah Z:/Protected Test Root ditolak oleh pengaman uji: {path}")


def env_server(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Lingkungan server tanpa kredensial host atau sakelar injeksi uji."""
    rahasia = re.compile(r"(?:API[_-]?KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)", re.IGNORECASE)
    env = {
        k: v for k, v in os.environ.items()
        if k not in ("MEMORI_GUARD_TEST", "MEMORI_GUARD_FAULT") and not rahasia.search(k)
    }
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUTF8", "1")
    if extra:
        env.update({k: v for k, v in extra.items() if not rahasia.search(k)})
    return env


def cwd_server() -> str | None:
    cwd = os.environ.get("MEMORI_GUARD_CWD", "").strip()
    return cwd or None


class KlienMcp:
    """Satu proses server `memori-guard` dan satu sesi MCP di atasnya."""

    def __init__(self, vault: Path, *, env_extra: dict[str, str] | None = None,
                 log_dir: Path | None = None, nama: str = "server",
                 argumen_tambahan: list[str] | None = None):
        cmd = perintah_server()
        if cmd is None:
            raise RuntimeError("MEMORI_GUARD_CMD tidak diisi")
        pastikan_bukan_vault_aktif(vault)
        self.vault = Path(vault)
        self.nama = nama
        self._next_id = 0
        self._lock = threading.Lock()
        self._antrian: "queue.Queue[dict[str, Any] | None]" = queue.Queue()
        log_dir = log_dir or self.vault.parent
        self.stderr_path = Path(log_dir) / f"{nama}-{os.getpid()}-{int(time.time() * 1000)}.stderr.txt"
        self._stderr = open(self.stderr_path, "wb")
        self.proc = subprocess.Popen(
            [*cmd, "--vault", str(self.vault), *(argumen_tambahan or [])],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self._stderr,
            env=env_server(env_extra),
            cwd=cwd_server(),
        )
        self._pembaca = threading.Thread(target=self._baca_stdout, daemon=True)
        self._pembaca.start()
        self.info_server = self._inisialisasi()

    # -- transport -------------------------------------------------------
    def _baca_stdout(self) -> None:
        assert self.proc.stdout is not None
        for baris in self.proc.stdout:
            baris = baris.strip()
            if not baris:
                continue
            try:
                self._antrian.put(json.loads(baris.decode("utf-8")))
            except (UnicodeDecodeError, json.JSONDecodeError):
                # Bukan pesan JSON-RPC (mis. log yang salah arah ke stdout); abaikan.
                continue
        self._antrian.put(None)

    def _kirim(self, pesan: dict[str, Any]) -> None:
        data = (json.dumps(pesan, ensure_ascii=False) + "\n").encode("utf-8")
        assert self.proc.stdin is not None
        try:
            self.proc.stdin.write(data)
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise ResponsHilang(f"{self.nama}: gagal mengirim ke server: {exc}") from exc

    def _id_baru(self) -> int:
        with self._lock:
            self._next_id += 1
            return self._next_id

    def _minta(self, method: str, params: dict[str, Any] | None, timeout: float) -> dict[str, Any]:
        req_id = self._id_baru()
        pesan: dict[str, Any] = {"jsonrpc": "2.0", "id": req_id, "method": method}
        if params is not None:
            pesan["params"] = params
        self._kirim(pesan)
        batas = time.monotonic() + timeout
        while True:
            sisa = batas - time.monotonic()
            if sisa <= 0:
                raise ResponsHilang(f"{self.nama}: tidak ada respons untuk {method} dalam {timeout} detik")
            try:
                masuk = self._antrian.get(timeout=sisa)
            except queue.Empty:
                continue
            if masuk is None:
                self._antrian.put(None)
                raise ResponsHilang(f"{self.nama}: server berhenti sebelum menjawab {method}")
            if "method" in masuk and "id" in masuk:
                self._jawab_permintaan_server(masuk)
                continue
            if "method" in masuk:
                continue  # notifikasi dari server
            if masuk.get("id") != req_id:
                continue
            if "error" in masuk:
                raise GalatMcp(masuk["error"])
            return masuk.get("result") or {}

    def _jawab_permintaan_server(self, masuk: dict[str, Any]) -> None:
        if masuk.get("method") == "ping":
            self._kirim({"jsonrpc": "2.0", "id": masuk["id"], "result": {}})
        else:
            self._kirim({"jsonrpc": "2.0", "id": masuk["id"],
                         "error": {"code": -32601, "message": "tidak didukung klien uji"}})

    def _inisialisasi(self) -> dict[str, Any]:
        hasil = self._minta("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "memori-guard-uji", "version": "1"},
        }, DEFAULT_TIMEOUT)
        self._kirim({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return hasil

    # -- API -------------------------------------------------------------
    def daftar_tool(self) -> list[str]:
        return [t.get("name") for t in self.daftar_tool_lengkap()]

    def daftar_tool_lengkap(self) -> list[dict[str, Any]]:
        """Definisi tool apa adanya dari `tools/list` (nama, deskripsi, inputSchema)."""
        hasil = self._minta("tools/list", {}, DEFAULT_TIMEOUT)
        return list(hasil.get("tools", []))

    def panggil(self, tool: str, timeout: float = DEFAULT_TIMEOUT, **argumen: Any) -> Any:
        """Panggil tool dan kembalikan nilai kembali JSON-nya (objek atau array)."""
        hasil = self._minta("tools/call", {"name": tool, "arguments": argumen}, timeout)
        return urai_hasil_tool(hasil)

    def tutup(self, timeout: float = 10) -> None:
        try:
            if self.proc.stdin and not self.proc.stdin.closed:
                self.proc.stdin.close()
        except OSError:
            pass
        try:
            self.proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=timeout)
        self._stderr.close()

    def tunggu_berhenti(self, timeout: float = 30) -> int:
        """Tunggu proses server berhenti sendiri (dipakai pada fault `henti_*`)."""
        kode = self.proc.wait(timeout=timeout)
        self._stderr.close()
        return kode

    def stderr(self) -> str:
        try:
            return self.stderr_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    def __enter__(self) -> "KlienMcp":
        return self

    def __exit__(self, *exc: object) -> None:
        if self.proc.poll() is None:
            self.tutup()
        elif not self._stderr.closed:
            self._stderr.close()


def urai_hasil_tool(hasil: dict[str, Any]) -> Any:
    """Ambil nilai kembali tool dari `CallToolResult`.

    Urutan: `structuredContent` (dengan pembungkus `{"result": ...}` dibuka jika
    hanya itu isinya), lalu teks JSON di `content`. Jika server menandai
    `isError` dan tidak ada JSON, kembalikan `{"_is_error": True, "_teks": ...}`.
    """
    struktur = hasil.get("structuredContent")
    if isinstance(struktur, dict):
        if set(struktur) == {"result"}:
            return struktur["result"]
        return struktur
    bagian_teks = [b.get("text", "") for b in hasil.get("content", []) if b.get("type") == "text"]
    if len(bagian_teks) > 1:
        # Beberapa server memecah nilai array menjadi satu blok teks per elemen.
        try:
            return [json.loads(t) for t in bagian_teks]
        except json.JSONDecodeError:
            pass
    teks = "".join(bagian_teks)
    try:
        return json.loads(teks)
    except json.JSONDecodeError:
        return {"_is_error": bool(hasil.get("isError")), "_teks": teks}


def perintah_python() -> list[str] | None:
    """Interpreter server: token `MEMORI_GUARD_CMD` sebelum `-m`. None jika tidak ada `-m`."""
    cmd = perintah_server()
    if cmd is None or "-m" not in cmd:
        return None
    return cmd[: cmd.index("-m")]


def jalankan_periksa(vault: Path, operasi: dict[str, Any], timeout: float = 60) -> tuple[subprocess.CompletedProcess, Any]:
    """Amandemen 1 A.1: `<python> -m claude_obsidian.memori_validasi --periksa`, operasi JSON di stdin.

    `--vault` ikut dikirim karena pemeriksaan hanya-tambah butuh byte Log lama
    (lihat laporan, ambiguitas terbuka).
    """
    py = perintah_python()
    if py is None:
        raise RuntimeError("interpreter tidak bisa diturunkan dari MEMORI_GUARD_CMD (tidak ada `-m`)")
    pastikan_bukan_vault_aktif(vault)
    proses = subprocess.run(
        [*py, "-m", "claude_obsidian.memori_validasi", "--periksa", "--vault", str(vault)],
        input=json.dumps(operasi, ensure_ascii=False).encode("utf-8"),
        capture_output=True,
        env=env_server(),
        cwd=cwd_server(),
        timeout=timeout,
    )
    try:
        hasil = json.loads(proses.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        hasil = None
    return proses, hasil


ENV_BANGUN_INDEKS = "MEMORI_GUARD_BUILD_INDEX_CMD"
PENANDA_VAULT = "{vault}"
# Amandemen 4 §6: kode keluar 0 (diperbarui) dan 2 (sudah sinkron) berhasil; 1 gagal.
KODE_BANGUN_BERHASIL = (0, 2)


def perintah_bangun_indeks() -> list[str] | None:
    """Urai `MEMORI_GUARD_BUILD_INDEX_CMD` (amandemen 4 §6: array JSON). None jika tidak diisi."""
    return _urai_perintah(ENV_BANGUN_INDEKS)


def argv_bangun_indeks(vault: Path) -> list[str]:
    """Token `{vault}` (amandemen 4 §6) diganti path vault sementara; tanpa token itu perintah ditolak."""
    cmd = perintah_bangun_indeks()
    if cmd is None:
        raise RuntimeError(f"{ENV_BANGUN_INDEKS} tidak diisi")
    if not any(PENANDA_VAULT in t for t in cmd):
        raise ValueError(f"{ENV_BANGUN_INDEKS} harus memuat token {PENANDA_VAULT} (amandemen 4 §6): {cmd!r}")
    v = str(vault)
    argv = [t.replace(PENANDA_VAULT, v) for t in cmd]
    pastikan_bukan_vault_aktif(vault)
    for token in argv:  # perintah yang menyebut vault aktif secara langsung juga ditolak
        if "my drive" in token.lower() and di_bawah_my_drive(token):
            raise VaultAktifTerdeteksi(f"{ENV_BANGUN_INDEKS} menyebut path di bawah Z:/Protected Test Root: {token}")
    return argv


def jalankan_bangun_indeks(vault: Path, timeout: float | None = None) -> subprocess.CompletedProcess:
    """Bangun indeks BM25 untuk vault sementara dengan perintah dari Hermes. Tes tidak membuat indeks sendiri."""
    batas = timeout if timeout is not None else float(os.environ.get("MEMORI_GUARD_BUILD_INDEX_TIMEOUT", "300"))
    return subprocess.run(
        argv_bangun_indeks(vault),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        env=env_server(),
        cwd=cwd_server(),
        timeout=batas,
    )


def jalankan_pulihkan(vault: Path, operation_id: str, timeout: float = 120) -> subprocess.CompletedProcess:
    """Perintah administratif kontrak bagian 5: `... --vault <vault> --pulihkan <operation_id>`."""
    cmd = perintah_server()
    if cmd is None:
        raise RuntimeError("MEMORI_GUARD_CMD tidak diisi")
    pastikan_bukan_vault_aktif(vault)
    return subprocess.run(
        [*cmd, "--vault", str(vault), "--pulihkan", operation_id],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        env=env_server(),
        cwd=cwd_server(),
        timeout=timeout,
    )
