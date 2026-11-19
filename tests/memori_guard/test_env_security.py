"""Ensure the black-box server subprocess does not inherit host credentials."""

from __future__ import annotations

from mcp_klien import env_server


def test_server_environment_filters_credentials(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-test-value")
    monkeypatch.setenv("GITHUB_TOKEN", "synthetic-test-value")
    monkeypatch.setenv("SAFE_TEST_FLAG", "preserved")
    monkeypatch.setenv("MEMORI_GUARD_FAULT", "injected")

    result = env_server()

    assert "OPENAI_API_KEY" not in result
    assert "GITHUB_TOKEN" not in result
    assert result["SAFE_TEST_FLAG"] == "preserved"
    assert "MEMORI_GUARD_FAULT" not in result


def test_explicit_nonsecret_test_environment_is_preserved(monkeypatch):
    monkeypatch.setenv("SAFE_TEST_FLAG", "parent")

    result = env_server({"SAFE_TEST_FLAG": "child", "MEMORI_GUARD_TEST": "1"})

    assert result["SAFE_TEST_FLAG"] == "child"
    assert result["MEMORI_GUARD_TEST"] == "1"
