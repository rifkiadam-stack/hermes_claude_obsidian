"""Builder-owned tests for the read-only ``cari`` tool (Fase E).

These are the author's own regression tests; Claude Code keeps its independent
suite.  Every test builds a throwaway vault locally, provisions a real BM25
index with the shipped adapter, and never touches the active vault.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

CORE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CORE))

from claude_obsidian.memori_guard_mcp import MemoryGuard  # noqa: E402
from claude_obsidian import memori_retrieval as retrieval  # noqa: E402

LONG_PAGE = """---
title: Kurva Imbal Hasil Panjang
type: catatan
status: aktif
created: 2026-11-18
updated: 2026-11-18
---

# Kurva Imbal Hasil Panjang

Yield curve pada tenor pendek bergerak turun. Dealer melihat spread tenor dua
tahun menyempit, sementara lelang tenor panjang tetap diserap bank dan asuransi.

Paragraf kedua membahas yield curve lagi dari sisi permintaan. Segmen investor
domestik menyerap seri benchmark, dan kepemilikan asing turun tipis pada bulan
berjalan. Dealer mencatat bahwa yield curve tidak lagi terbalik penuh.
"""

SECOND_PAGE = """---
created: 2026-11-18
updated: 2026-11-18
---

# Segmen Investor

Segmen investor asuransi dan dana pensiun menyerap lelang tenor panjang.
"""

SESSION_PAGE = """---
title: Catatan Sesi Cari
type: sesi
status: aktif
created: 2026-11-18
updated: 2026-11-18
---

# Catatan Sesi Cari

Catatan kerja mengenai yield curve untuk pengujian pencarian.
"""


def _provision(vault: Path) -> None:
    script = CORE / "scripts" / "bm25_provision_native.py"
    proc = subprocess.run(
        [sys.executable, "-B", str(script), "--vault", str(vault)],
        capture_output=True, text=True, timeout=300,
    )
    if proc.returncode not in (0, 2):
        raise AssertionError(f"provisioning failed: {proc.returncode}: {proc.stdout}{proc.stderr}")


class CariTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        vault = Path(cls._tmp.name) / "vault"
        for folder in ("wiki/uji", "wiki/sesi", "wiki/profil", "sesi-log"):
            (vault / folder).mkdir(parents=True, exist_ok=True)
        (vault / "wiki/uji/kurva.md").write_text(LONG_PAGE, encoding="utf-8", newline="\n")
        (vault / "wiki/uji/segmen.md").write_text(SECOND_PAGE, encoding="utf-8", newline="\n")
        (vault / "wiki/sesi/uji-sesi.md").write_text(SESSION_PAGE, encoding="utf-8", newline="\n")
        (vault / "wiki/uji/.tersembunyi.md").write_text(
            "---\ntitle: Tersembunyi\n---\n\n# Tersembunyi\n", encoding="utf-8", newline="\n")
        (vault / "sesi-log/uji-log.md").write_text(
            "---\ntitle: Log Uji\ntype: sesi-log\n---\n\n# Log Uji\n", encoding="utf-8", newline="\n")
        _provision(vault)
        cls.vault = vault
        cls.guard = MemoryGuard(vault)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    # ---- cari: shape, ordering, dedup ----
    def test_cari_returns_one_result_per_page_with_contracted_fields(self):
        result = self.guard.cari("yield curve", 5)
        self.assertEqual(result["status"], "selesai", result)
        self.assertIn("dibangun", result["indeks"])
        self.assertTrue(result["indeks"]["dibangun"].endswith("Z"))
        self.assertIsInstance(result["indeks"]["basi"], bool)

        paths = [item["path"] for item in result["hasil"]]
        self.assertEqual(len(paths), len(set(paths)), "one result per page")
        self.assertIn("wiki/uji/kurva.md", paths)

        scores = [item["skor"] for item in result["hasil"]]
        self.assertEqual(scores, sorted(scores, reverse=True))
        for item in result["hasil"]:
            self.assertEqual(set(item), {"path", "judul", "type", "skor", "cuplikan"})
            self.assertLessEqual(len(item["cuplikan"]), 500)
            self.assertTrue(item["path"].startswith("wiki/"))

        long_page = next(item for item in result["hasil"] if item["path"] == "wiki/uji/kurva.md")
        self.assertEqual(long_page["judul"], "Kurva Imbal Hasil Panjang")
        self.assertEqual(long_page["type"], "catatan")

        indexed = retrieval.score(
            retrieval.load_snapshot(self.vault), "yield curve", top_k=50)
        self.assertGreaterEqual(len(indexed), 1, "index must return matching chunks")
        self.assertLessEqual(len(paths), len(indexed), "pages are deduplicated from chunks")

    def test_cari_title_falls_back_to_h1_then_stem(self):
        result = self.guard.cari("segmen investor", 5)
        titles = {item["path"]: item["judul"] for item in result["hasil"]}
        self.assertEqual(titles.get("wiki/uji/segmen.md"), "Segmen Investor")

    def test_cari_respects_jumlah_limit(self):
        result = self.guard.cari("yield curve", 1)
        self.assertEqual(result["status"], "selesai")
        self.assertEqual(len(result["hasil"]), 1)

    # ---- cari: input validation comes before index checks ----
    def test_cari_rejects_invalid_input(self):
        for kueri, jumlah in (("", 5), ("   ", 5), ("x" * 501, 5),
                              ("yield", 0), ("yield", 11), ("yield", True)):
            with self.subTest(kueri=kueri[:12], jumlah=jumlah):
                result = self.guard.cari(kueri, jumlah)
                self.assertEqual(result["status"], "ditolak", result)

    def test_invalid_query_wins_over_missing_index(self):
        index = self.vault / ".vault-meta/bm25/index.json"
        saved = index.read_bytes()
        index.unlink()
        try:
            self.assertEqual(self.guard.cari("", 5)["status"], "ditolak")
            missing = self.guard.cari("yield curve", 5)
            self.assertEqual(missing["status"], "gagal")
            self.assertIn("Hermes", missing["pesan"])
        finally:
            index.write_bytes(saved)

    def test_corrupt_index_is_reported_as_gagal(self):
        index = self.vault / ".vault-meta/bm25/index.json"
        saved = index.read_bytes()
        index.write_bytes(b"{not json")
        try:
            result = self.guard.cari("yield curve", 5)
            self.assertEqual(result["status"], "gagal")
        finally:
            index.write_bytes(saved)

    # ---- basi ----
    def test_basi_true_after_page_edit_and_false_again_after_rebuild(self):
        page = self.vault / "wiki/uji/segmen.md"
        original = page.read_text(encoding="utf-8")
        try:
            self.assertFalse(self.guard.cari("segmen investor", 2)["indeks"]["basi"])
            page.write_text(original + "\nTambahan tanpa rebuild.\n", encoding="utf-8", newline="\n")
            self.assertTrue(self.guard.cari("segmen investor", 2)["indeks"]["basi"])
        finally:
            page.write_text(original, encoding="utf-8", newline="\n")
            _provision(self.vault)

    def test_basi_true_when_page_added_or_removed(self):
        extra = self.vault / "wiki/uji/tambahan.md"
        try:
            extra.write_text("---\ntitle: Tambahan\n---\n\n# Tambahan\n", encoding="utf-8", newline="\n")
            self.assertTrue(self.guard.cari("tambahan", 2)["indeks"]["basi"])
        finally:
            extra.unlink()
        page = self.vault / "wiki/uji/segmen.md"
        original = page.read_text(encoding="utf-8")
        moved = self.vault / "wiki/uji/segmen-lama.md"
        try:
            page.rename(moved)
            self.assertTrue(self.guard.cari("segmen", 2)["indeks"]["basi"])
        finally:
            moved.rename(page)
            self.assertEqual(page.read_text(encoding="utf-8"), original)

    def test_adapter_accepts_path_that_needs_normalisation(self):
        """Regression: an unresolved/8.3-style path must not break provisioning."""
        weird = str(self.vault / "wiki" / "..")
        proc = subprocess.run(
            [sys.executable, "-B", str(CORE / "scripts" / "bm25_provision_native.py"),
             "--vault", weird],
            capture_output=True, text=True, timeout=300)
        self.assertIn(proc.returncode, (0, 2), proc.stdout + proc.stderr)

    # ---- baca scope ----
    def test_baca_reads_wiki_page_and_rejects_write(self):
        read = self.guard.baca("wiki/uji/segmen.md")
        self.assertEqual(read["status"], "selesai")
        self.assertTrue(read["ada"])
        self.assertTrue(read["sha256"].startswith("sha256:"))

        denied = self.guard.tulis(
            "id: #uji-tolak-wiki",
            [{"path": "wiki/uji/segmen.md", "isi_baru": "x", "hash_lama": None}], [], "uji")
        self.assertEqual(denied["status"], "ditolak")

    def test_dot_components_rejected_in_every_scope(self):
        cases = [
            "wiki/uji/.tersembunyi.md",
            "wiki/sesi/.tersembunyi.md",
            ".vault-meta/bm25/index.json",
            "wiki/.draft/halaman.md",
        ]
        for path in cases:
            with self.subTest(path=path):
                self.assertEqual(self.guard.baca(path)["status"], "ditolak")
        write = self.guard.tulis(
            "id: #uji-tolak-titik",
            [{"path": "wiki/sesi/.tersembunyi.md", "isi_baru": "x", "hash_lama": None}], [], "uji")
        self.assertEqual(write["status"], "ditolak")

    def test_daftar_scope_unchanged(self):
        denied = self.guard.daftar("wiki")
        self.assertIsInstance(denied, dict)
        self.assertEqual(denied["status"], "ditolak")
        listed = self.guard.daftar("wiki/sesi")
        self.assertIsInstance(listed, list)
        self.assertEqual([item["path"] for item in listed], ["wiki/sesi/uji-sesi.md"])

    # ---- Amandemen 5: bentuk hasil dan aturan tambahan ----
    def test_type_is_null_when_frontmatter_has_no_type(self):
        result = self.guard.cari("segmen investor", 5)
        item = next(i for i in result["hasil"] if i["path"] == "wiki/uji/segmen.md")
        self.assertIn("type", item)
        self.assertIsNone(item["type"])

    def test_snippet_is_literal_window_of_page_content(self):
        result = self.guard.cari("yield curve", 5)
        self.assertTrue(result["hasil"])
        for item in result["hasil"]:
            page_text = (self.vault / item["path"]).read_text(encoding="utf-8")
            normalised_page = " ".join(page_text.split())
            normalised_snippet = " ".join(item["cuplikan"].split())
            self.assertIn(normalised_snippet, normalised_page, item["path"])

    def test_rejected_and_failed_payloads_only_carry_status_and_message(self):
        rejected = self.guard.cari("", 5)
        self.assertEqual(set(rejected), {"status", "pesan"})
        index = self.vault / ".vault-meta/bm25/index.json"
        saved = index.read_bytes()
        index.unlink()
        try:
            failed = self.guard.cari("yield curve", 5)
        finally:
            index.write_bytes(saved)
        self.assertEqual(failed["status"], "gagal")
        self.assertEqual(set(failed), {"status", "pesan"})
        self.assertIn("Hermes", failed["pesan"])

    def test_query_length_is_measured_after_stripping_edges(self):
        padded = "  " + ("y" * 500) + "  "
        self.assertEqual(self.guard.cari(padded, 1)["status"], "selesai")
        self.assertEqual(self.guard.cari("z" * 501, 1)["status"], "ditolak")
        self.assertEqual(self.guard.cari("   ", 1)["status"], "ditolak")

    def test_wrong_types_are_rejected_or_protocol_errors(self):
        for jumlah in ("5", 2.5, None):
            with self.subTest(jumlah=jumlah):
                try:
                    result = self.guard.cari("yield", jumlah)
                except (TypeError, ValueError):
                    continue
                self.assertEqual(result["status"], "ditolak")

    def test_non_markdown_and_missing_wiki_page(self):
        txt = self.vault / "wiki/uji/catatan.txt"
        txt.write_text("bukan markdown", encoding="utf-8")
        try:
            self.assertEqual(self.guard.baca("wiki/uji/catatan.txt")["status"], "ditolak")
        finally:
            txt.unlink()
        missing = self.guard.baca("wiki/uji/tidak-ada.md")
        self.assertEqual(missing["status"], "selesai")
        self.assertFalse(missing["ada"])

    def test_daftar_hides_dotted_entries(self):
        dotted_dir = self.vault / "wiki/sesi/.arsip"
        dotted_dir.mkdir(exist_ok=True)
        (dotted_dir / "lama.md").write_text("# lama", encoding="utf-8")
        dotted_file = self.vault / "wiki/sesi/.tersembunyi.md"
        dotted_file.write_text("# sembunyi", encoding="utf-8")
        try:
            listed = self.guard.daftar("wiki/sesi")
            paths = [item["path"] for item in listed]
            self.assertIn("wiki/sesi/uji-sesi.md", paths)
            self.assertFalse([p for p in paths if ".arsip" in p or ".tersembunyi" in p])
        finally:
            (dotted_dir / "lama.md").unlink()
            dotted_dir.rmdir()
            dotted_file.unlink()

    def test_zero_score_pages_are_not_returned(self):
        result = self.guard.cari("yield curve", 10)
        self.assertTrue(all(item["skor"] > 0 for item in result["hasil"]))

    # ---- Fase F: temuan Claude Code ----
    def test_jumlah_rejects_truthy_non_integers(self):
        for jumlah in ("5", "5.0", 5.0, True, None):
            with self.subTest(jumlah=jumlah):
                try:
                    result = self.guard.cari("yield curve", jumlah)
                except (TypeError, ValueError):
                    continue
                self.assertEqual(result["status"], "ditolak", result)
        self.assertEqual(self.guard.cari("yield curve", 5)["status"], "selesai")

    def test_page_in_results_can_be_deleted_immediately_after_cari(self):
        result = self.guard.cari("segmen investor", 5)
        self.assertEqual(result["status"], "selesai")
        target = next(item["path"] for item in result["hasil"]
                      if item["path"] == "wiki/uji/segmen.md")
        page = self.vault / target
        backup = page.read_bytes()
        try:
            page.unlink()  # WinError 32 would surface here if a handle leaked
            self.assertFalse(page.exists())
        finally:
            page.write_bytes(backup)
            _provision(self.vault)

    def test_cari_never_fails_while_index_is_republished(self):
        import threading
        page = self.vault / "wiki/uji/kurva.md"
        original = page.read_text(encoding="utf-8")
        statuses: list[str] = []
        stop = threading.Event()

        def reader() -> None:
            while not stop.is_set():
                statuses.append(self.guard.cari("yield curve", 3)["status"])

        thread = threading.Thread(target=reader)
        thread.start()
        codes: list[int] = []
        try:
            for attempt in range(5):
                page.write_text(original + "Variasi %d." % attempt,
                                encoding="utf-8")
                proc = subprocess.run(
                    [sys.executable, "-B",
                     str(CORE / "scripts" / "bm25_provision_native.py"),
                     "--vault", str(self.vault)],
                    capture_output=True, text=True, timeout=300)
                codes.append(proc.returncode)
                self.assertIn(proc.returncode, (0, 2), proc.stdout + proc.stderr)
        finally:
            stop.set()
            thread.join(timeout=60)
            page.write_text(original, encoding="utf-8")
            _provision(self.vault)
        self.assertTrue(statuses, "reader thread must have queried")
        self.assertEqual({"selesai"}, set(statuses), statuses[:5])


if __name__ == "__main__":
    unittest.main()
