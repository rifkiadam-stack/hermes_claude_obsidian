#!/usr/bin/env python3
"""Hermetic contracts for the Hermes host adapter."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class HermesAdapterContractTests(unittest.TestCase):
    def adapter(self) -> dict:
        return json.loads(
            (ROOT / "config" / "hermes-adapter.json").read_text(encoding="utf-8")
        )

    def test_adapter_maps_every_upstream_skill_without_reducing_scope(self) -> None:
        adapter = self.adapter()
        discovered = {
            path.parent.name for path in (ROOT / "skills").glob("*/SKILL.md")
        }
        mappings = {item["upstream"]: item for item in adapter["skills"]}
        self.assertEqual(15, len(discovered))
        self.assertEqual(discovered, set(mappings))
        self.assertTrue(all(item["treatment"] != "remove" for item in mappings.values()))

    def test_adapter_uses_hermes_tools_and_keeps_vault_outside_memory(self) -> None:
        adapter = self.adapter()
        self.assertEqual(
            {
                "Read": "read_file",
                "Grep": "search_files",
                "Glob": "search_files",
                "Write": "write_file",
                "Edit": "patch",
                "Bash": "terminal",
                "Task": "delegate_task",
            },
            adapter["tool_map"],
        )
        self.assertEqual("external-vault", adapter["knowledge_boundary"]["vault"])
        self.assertEqual("agent-context", adapter["knowledge_boundary"]["memory"])
        self.assertFalse(adapter["knowledge_boundary"]["interchangeable"])
        selection = adapter["vault_selection"]
        self.assertIsNone(selection["configured_path"])
        self.assertEqual("HERMES_OBSIDIAN_VAULT", selection["configuration_key"])

    def test_adapter_declares_reduced_windows_guarantees_honestly(self) -> None:
        policy = self.adapter()["native_windows_write_policy"]
        self.assertEqual("hermes-native-windows-reduced-v1", policy["schema"])
        self.assertEqual("single-orchestrator", policy["writer_model"])
        self.assertTrue(policy["expected_content_recheck"])
        self.assertTrue(policy["checkpoint_before_multi_file_write"])
        self.assertTrue(policy["verify_after_write"])
        self.assertTrue(policy["lint_after_write"])
        self.assertFalse(policy["claims_upstream_transaction_equivalence"])
        self.assertEqual("abort", policy["on_concurrent_drift"])

    def test_adapter_preserves_agents_as_explicit_delegation_contracts(self) -> None:
        agents = {item["upstream"]: item for item in self.adapter()["agents"]}
        self.assertEqual(
            {"wiki-ingest", "wiki-lint", "verifier"}, set(agents)
        )
        self.assertTrue(all(item["runtime"] == "delegate_task" for item in agents.values()))
        self.assertTrue(all(item["writes"] is False for item in agents.values()))
        for agent in agents.values():
            template_path = agent.get("template_path")
            self.assertIsInstance(template_path, str)
            template = ROOT / template_path
            self.assertTrue(template.is_file(), template_path)
            text = template.read_text(encoding="utf-8")
            self.assertIn("delegate_task", text)
            self.assertIn("writes: false", text)
            self.assertNotIn("model: sonnet", text)

    def test_native_windows_documentation_discloses_limits_and_safe_sequence(self) -> None:
        guide = (ROOT / "docs" / "hermes-native-windows.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("reduced-guarantee", guide)
        self.assertIn("not equivalent", guide)
        self.assertIn("inspect_operation", guide)
        self.assertIn("prepare_operation", guide)
        self.assertIn("write_file", guide)
        self.assertIn("patch", guide)
        self.assertIn(
            "verify_operation(vault, operation, approved_plan_sha256)", guide
        )
        self.assertIn(
            "rollback_operation(vault, operation, approved_plan_sha256)", guide
        )
        self.assertIn("single orchestrator", guide)
        self.assertIn("Obsidian", guide)


if __name__ == "__main__":
    unittest.main()
