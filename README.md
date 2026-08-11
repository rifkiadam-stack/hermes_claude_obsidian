# hermes_claude_obsidian

**claude-obsidian, adapted for [Hermes Agent](https://hermes-agent.nousresearch.com) on native Windows (no WSL).**

This is a port of [AgriciDaniel/claude-obsidian](https://github.com/AgriciDaniel/claude-obsidian) — a local-first Agent Skills package for building source-cited, compounding Obsidian knowledge bases. The 15 upstream skills and the deterministic Python core are preserved; the host boundary (Claude Code / POSIX transactions) is replaced with Hermes Agent tooling and a reduced-guarantee native-Windows write guard.

> **Status: beta.** This is a personal port maintained on a best-effort basis. It works and is security-reviewed, but it has not seen long production use. See [Limitations](#limitations).

---

## Why this port exists

Upstream claude-obsidian is built around a POSIX transaction engine (`O_DIRECTORY`, `dir_fd`, `flock`, atomic replacement). On native Windows it **fails closed** (`UNSUPPORTED_PLATFORM`) and refuses vault mutations by design. If you use Windows without WSL and want a Hermes-hosted Second Brain, this port provides:

- **All 15 skills** working as Hermes skills (trigger routing, Hermes tool mapping).
- **A native-Windows write guard** (`claude_obsidian/hermes_windows_write.py`) that replaces the POSIX transaction engine with a serialized, expected-hash, checkpointed, verifiable, rollback-capable flow — with honestly reduced guarantees.
- **Hermes delegation templates** for the three upstream agent roles (ingest worker, lint worker, verifier).

## Differences from upstream

| Area | Upstream | This port |
|---|---|---|
| Host | Claude Code / Claude hooks | Hermes Agent (`read_file`, `search_files`, `write_file`, `patch`, `delegate_task`, `terminal`) |
| Vault mutations | POSIX transaction core (Linux/WSL) | Native-Windows write guard (reduced guarantee) |
| Skill frontmatter | `name` + `description` only | Full Hermes metadata (version, author, license, platforms, tags, related skills) |
| Vault selection | `CLAUDE_OBSIDIAN_VAULT` | `HERMES_OBSIDIAN_VAULT` (legacy env still honored by core scripts) |
| Skill names | Claude slash commands | Plain Hermes skill names under the `second-brain` category |

The Python core (`claude_obsidian/`), deterministic lint, BM25 retrieval, ledgers/provenance, and templates are preserved as upstream.

## Quick start (Hermes on Windows)

1. **Clone and install the skills**

   ```powershell
   git clone https://github.com/rifkiadam-stack/hermes_claude_obsidian.git
   # copy skills/* into your Hermes profile skills dir, e.g. under skills/second-brain/
   ```

2. **Set the runtime environment** in your Hermes profile `.env` (forward slashes):

   ```text
   HERMES_OBSIDIAN_VAULT=<path-to-your-obsidian-vault>
   HERMES_CLAUDE_OBSIDIAN_CORE=C:/path/to/hermes_claude_obsidian
   ```

3. **Adopt an existing vault or init a new one** (dry-run first; apply goes through the write guard, never `--apply` on Windows):

   ```bash
   python scripts/claude-obsidian.py adopt "C:/path/to/vault" --generated-at 2026-01-01T00:00:00Z --operation-id my-adopt
   python scripts/claude-obsidian.py init "C:/path/to/new-vault"   # dry-run
   ```

4. **Start a new Hermes session** so the skill router picks up the package, then talk naturally:

   - "simpan ini ke second brain" / "save this to the vault" → `save`
   - "tanya wiki: ..." / "query the wiki: ..." → `wiki-query`
   - "ingest this file" → `wiki-ingest`, "lint wiki" → `wiki-lint`
   - "cari di wiki: ..." → `wiki-retrieve` (BM25), "riset topik X" → `autoresearch`

## The 15 skills

| Skill | Role |
|---|---|
| `wiki` | Route vault setup, adoption, and wiki workflows |
| `save` | Save explicit selections to the vault (never auto-capture) |
| `wiki-ingest` | Ingest files, pages, and sources into the vault |
| `wiki-query` | Read-only, evidence-grounded answers from the vault |
| `wiki-lint` | Deterministic lint of vault health and provenance |
| `wiki-retrieve` | BM25 chunk retrieval |
| `wiki-mode` | LYT / PARA / Zettelkasten routing |
| `wiki-fold` | Fold log entries into bounded summaries |
| `autoresearch` | Bounded source-grounded research dossier |
| `defuddle` | Clean a URL into readable, citable content |
| `wiki-cli` | Vault transport via file tools / CLI |
| `obsidian-markdown` | Obsidian Flavored Markdown validation |
| `obsidian-bases` | Obsidian Bases view definitions |
| `canvas` | Obsidian JSON Canvas files |
| `think` | Second Brain reasoning review (narrowed trigger) |

## Write guard (native Windows)

Every vault mutation runs through `hermes_windows_write`:

```
inspect_operation(vault, operation)      -> approval_sha256
prepare_operation(vault, operation, approval)   (checkpoint + cooperative lock)
[external write via Hermes file tools]
verify_operation(vault, operation, approval)    (hash check, releases lock)
rollback_operation(vault, operation, approval)  (restores before-images)
```

It enforces: protected namespaces (`.git`, `.vault-meta/hermes-windows`), case-fold alias rejection, junction/symlink escape validation, strict finite JSON, bounded reads, streaming lock inspection, retriable lock release, and rollback that refuses unexplained drift. **Reduced guarantee**: single writer, expected-hash recheck, checkpoint, post-write verification, deterministic lint, rollback — it is not the POSIX transaction core. See `docs/hermes-native-windows.md`.

## Testing

```bash
python -B tests/test_hermes_skill_port.py     # 15-skill Hermes packaging contract
python -B tests/test_hermes_windows_write.py  # write-guard behavior (23 tests)
python -B tests/test_hermes_adapter.py        # host adapter contract
python -B tests/test_package_validation.py    # product package contract
python -B scripts/claude-obsidian.py package validate
```

`make` is not installed on this host; `make test` is not a supported entry point here. The upstream suite has platform-bound failures on native Windows (POSIX/symlink/WSL expectations) that are not regressions of this port.

## Limitations

- Vault mutations are **reduced-guarantee** (see above); avoid editing the same note in Obsidian while Hermes is writing.
- `contracts --verify` reports `degraded` for `wiki`/`wiki-cli`/`wiki-lint` on Windows: their behavioral verifiers require vault mutation, which the upstream core refuses on this platform by design. Capabilities remain `valid` with no config errors.
- Google-Drive-mounted vaults: sync may race writes; the guard rejects drift safely — retry the operation.
- The upstream Claude Code plugin files (`.claude-plugin/`) are preserved for structural fidelity but are not the supported path here.

## License

MIT — see [LICENSE](LICENSE). Original work © 2026 AgriciDaniel (AI Marketing Hub); Hermes/native-Windows adaptation © 2026 Rifki Adam. Upstream: https://github.com/AgriciDaniel/claude-obsidian
