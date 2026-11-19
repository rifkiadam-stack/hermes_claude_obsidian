# memori-guard: local setup

This guide describes generic setup for a local development checkout. Adapt paths and interpreter commands to your operating system; do not commit machine-specific paths, vault locations, or credentials.

1. Install the project dependencies using the repository's documented development setup.
2. Configure the MCP client to start `python -B -m claude_obsidian.memori_guard_mcp` with the repository root as its working directory.
3. Pass an explicit test-vault path and a conservative byte limit. Never point acceptance tests at a live vault.
4. Start the server through the client and confirm that the expected tools are discovered.
5. Use a synthetic fixture for acceptance tests. Keep any private sanitizer denylist outside the repository.

Example command (replace the placeholder with a disposable test vault):

```sh
python -B -m claude_obsidian.memori_guard_mcp --vault /path/to/test-vault --batas-byte 1048576
```

No repository change, test evidence, or result log should contain a user's local path or vault content. Run the repository's test target before proposing a commit. Publishing requires a separately approved action; this preparation does not authorize a push.
