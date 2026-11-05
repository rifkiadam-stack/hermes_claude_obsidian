# Hermes delegation template — wiki lint

```yaml
runtime: delegate_task
role: leaf
writes: false
network_egress: false
```

Use this template to run and interpret the deterministic linter against one explicitly selected vault or scope after all writers are idle.

## Worker contract

1. Parent supplies absolute product root, absolute vault root, and optional scope.
2. Run the canonical linter through `terminal` using the native Python interpreter and JSON output.
3. Preserve stdout, stderr, and exit status separately.
4. Validate surprising findings with `read_file`; do not replace the linter with an improvised scan.
5. Return exact path, line, rule, severity, diagnostic, and bounded repair proposal.
6. Never write a report into the vault, repair files, rebuild indexes, use the Windows write guard, mutate Git, or access the network.

## Required `delegate_task` output

```text
LINT STATUS: CLEAN | FINDINGS | TOOL-ERROR
VAULT: <resolved vault>
COMMAND: <command and exit code>
SUMMARY: <counts>
FINDINGS:
- path:line [rule/severity] — diagnostic
  evidence: <validated observation>
  proposed_repair: <proposal only>
TOOL CONCERNS: <none or evidence>
LIMITATIONS: <none or explicit limits>
```

Run this leaf after canonical writes, never in parallel with a writer, because lint is not snapshot-isolated.
