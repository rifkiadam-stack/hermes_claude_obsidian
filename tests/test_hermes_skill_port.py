#!/usr/bin/env python3
"""Hermes port contract: 15 skill surfaces, packaging, triggers, and routing."""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from claude_obsidian.package_validation import PORTABLE_SKILL_KEYS, _frontmatter  # noqa: E402

SKILLS_ROOT = ROOT / "skills"

FORBIDDEN_TOKENS = (
    "python3",
    "/claude-obsidian:",
    "Read(",
    "Bash(",
    "Write(",
    "Edit(",
    "Grep(",
    "Glob(",
)

MACHINE_LOCAL_PATH = re.compile(
    r"(?<![A-Za-z])[A-Za-z]:[\\/]|/c/Users|/c/users|G:[\\/]|My Drive"
)
SECRET_PATTERN = re.compile(
    r"(?i)(api[_-]?key|password|secret|token)\s*[:=]\s*[\"'][^\"']{6,}[\"']"
)
LEGACY_ENV = "CLAUDE_OBSIDIAN_VAULT"
HERMES_ENV = "HERMES_OBSIDIAN_VAULT"

# name -> (canonical related_skills, required trigger fragments)
EXPECTED = {
    "wiki": (["wiki-ingest", "wiki-query", "save", "wiki-lint", "wiki-fold", "autoresearch"], ("vault", "route")),
    "save": (["wiki-query", "wiki-ingest"], ("second brain", "explicit")),
    "wiki-ingest": (["save", "wiki-lint"], ("ingest",)),
    "wiki-query": (["wiki-lint", "wiki-retrieve"], ("read-only",)),
    "wiki-lint": (["wiki", "wiki-query"], ("lint", "deterministic")),
    "wiki-retrieve": (["wiki-query", "wiki-lint"], ("retriev",)),
    "wiki-mode": (["wiki"], ("mode",)),
    "wiki-fold": (["wiki", "wiki-query"], ("fold",)),
    "autoresearch": (["wiki", "wiki-ingest", "save"], ("research",)),
    "defuddle": (["wiki-ingest", "save"], ("clean",)),
    "wiki-cli": (["wiki", "wiki-query"], ("transport",)),
    "obsidian-markdown": (["wiki", "save"], ("obsidian",)),
    "obsidian-bases": (["wiki", "obsidian-markdown"], ("base",)),
    "canvas": (["wiki", "save"], ("canvas",)),
    "think": (["save"], ("second brain",)),
}

FORBIDDEN_IN_THINK = ("architecture", "postmortem", "debugging", "planning")


class HermesSkillPortTests(unittest.TestCase):
    def parse(self, path: Path):
        values, errors = _frontmatter(path, path.relative_to(ROOT).as_posix())
        return values, errors

    def skill_paths(self) -> list[Path]:
        return sorted(SKILLS_ROOT.glob("*/SKILL.md"))

    def test_all_fifteen_skills_are_present(self) -> None:
        names = {path.parent.name for path in self.skill_paths()}
        self.assertEqual(set(EXPECTED), names)

    def test_frontmatter_uses_canonical_hermes_shape(self) -> None:
        for path in self.skill_paths():
            values, errors = self.parse(path)
            self.assertEqual([], errors, path)
            self.assertEqual(
                tuple(values), PORTABLE_SKILL_KEYS, f"{path}: {tuple(values)}"
            )
            self.assertEqual(values["name"], path.parent.name, path)
            metadata = values["metadata"]
            self.assertIsInstance(metadata, dict, path)
            self.assertIn("hermes", metadata, path)

    def test_descriptions_are_short_and_self_contained(self) -> None:
        for path in self.skill_paths():
            values, _ = self.parse(path)
            description = values["description"]
            self.assertIsInstance(description, str, path)
            self.assertTrue(
                1 <= len(description) <= 60,
                f"{path}: description {len(description)} chars must be 1-60",
            )

    def test_metadata_tags_and_related_skills_are_valid(self) -> None:
        for path in self.skill_paths():
            values, _ = self.parse(path)
            hermes = values["metadata"]["hermes"]
            self.assertIsInstance(hermes["tags"], list, path)
            self.assertTrue(hermes["tags"], f"{path}: tags must be non-empty")
            self.assertIsInstance(hermes["related_skills"], list, path)
            self.assertEqual(
                hermes["related_skills"],
                EXPECTED[path.parent.name][0],
                f"{path}: related_skills mismatch",
            )
            self.assertIn("windows", values["platforms"], path)

    def test_no_claude_host_assumptions_in_bodies(self) -> None:
        for path in self.skill_paths():
            text = path.read_text(encoding="utf-8")
            for token in FORBIDDEN_TOKENS:
                self.assertNotIn(token, text, f"{path}: forbidden token {token!r}")
            self.assertIsNone(MACHINE_LOCAL_PATH.search(text), path)
            self.assertIsNone(SECRET_PATTERN.search(text), path)
            if LEGACY_ENV in text:
                self.assertIn(
                    HERMES_ENV,
                    text,
                    f"{path}: legacy env mention requires Hermes env wording",
                )

    def test_all_linked_references_exist(self) -> None:
        link = re.compile(r"\]\(references/([^)]+)\)")
        for path in self.skill_paths():
            text = path.read_text(encoding="utf-8")
            for name in link.findall(text):
                target = path.parent / "references" / name
                self.assertTrue(
                    target.is_file(),
                    f"{path}: missing reference references/{name}",
                )

    def test_trigger_routing_table(self) -> None:
        for name, (related, fragments) in EXPECTED.items():
            path = SKILLS_ROOT / name / "SKILL.md"
            values, _ = self.parse(path)
            description = values["description"].lower()
            for fragment in fragments:
                self.assertIn(
                    fragment, description, f"{name}: description lacks {fragment!r}"
                )
        think = self.parse(SKILLS_ROOT / "think" / "SKILL.md")[0]["description"].lower()
        for token in FORBIDDEN_IN_THINK:
            self.assertNotIn(token, think, f"think: generic trigger {token!r}")

    def test_template_vault_matches_core_paths(self) -> None:
        template = ROOT / "templates" / "vault"
        required = (
            ".gitignore",
            ".obsidian/app.json",
            ".obsidian/appearance.json",
            ".obsidian/graph.json",
            ".raw/.manifest.json",
            "inbox/.gitkeep",
            "wiki/hot.md",
            "wiki/index.md",
            "wiki/log.md",
            "wiki/overview.md",
        )
        for relative in required:
            self.assertTrue(
                (template / relative).is_file(), f"template missing {relative}"
            )
        for excluded in (".claude-plugin", ".vault-meta"):
            self.assertFalse(
                (template / excluded).exists(),
                f"template must not ship {excluded}",
            )


if __name__ == "__main__":
    unittest.main()
