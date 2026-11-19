# memori-guard

`memori-guard` provides a Model Context Protocol (MCP) stdio adapter over the native transaction guard in `claude_obsidian`. It exposes bounded read and write operations while reusing the core validation, checkpoint, and recovery mechanisms.

## Runtime

Run the service from the repository root with a supported Python interpreter:

```sh
python -B -m claude_obsidian.memori_guard_mcp --vault /path/to/test-vault --batas-byte 1048576
```

Always select the vault explicitly. For local MCP clients, configure the executable and working directory using paths appropriate to that machine. Do not place credentials, personal vault content, or machine-specific paths in shared configuration.

## Safety model

- Writes are validated and applied through the shared transaction guard.
- The selected vault is the boundary for all file operations.
- Recovery uses the original operation identity; callers must not blindly replay an operation with uncertain outcome.
- Read-only retrieval is limited to the supported knowledge areas and excludes hidden/private path components.
- Search indexes are derived data and may be reported stale or unavailable.

## Testing

The repository test suite contains unit, recovery, concurrency, and protocol-contract tests. Claude Code acceptance tests are under `tests/memori_guard/`; they use a synthetic fixture vault and require a locally configured server command. Evidence logs and local environment reports are intentionally not distributed.

Run the normal project test target from the repository root. Acceptance tests are skipped unless their documented local environment variables are configured.
