# Preservation audits and ingest-mode proposals

## Three different verification claims

1. **Input fidelity:** original-file bytes and archive bytes match, with input hash recorded before any mutation. A pasted message permits only a claim about the text actually received, not the sender's unseen original file.
2. **Internal consistency:** raw hash matches manifest and source ledger. This alone cannot establish fidelity to an unavailable original.
3. **Derivative fidelity:** summary retains the source's meaning, attribution and degree of certainty. Neither matching hashes nor a clean lint result proves this.

In a read-only audit, identify the exact source, read both archive and derivative, show concrete changes or additions with locators, and state which of the three claims has evidence. If original staging is gone, look for legitimate retained baseline evidence; do not fabricate or reconstruct an original. Do not rewrite notes while merely checking them.

Keep direct author statements separate from agent synthesis. A caveat can be useful, but inserting it into the source's voice changes the presentation. Preserve source numbers and contradictions; annotate discrepancies separately rather than silently fixing them.

## Reviewing a split into ordinary and verbatim modes

These are design distinctions, not permission to activate unapproved skills:

- Ordinary ingest: unchanged raw plus a faithful source summary when the compilation-value gate justifies it; agent analysis separately labeled.
- Verbatim ingest: unchanged source without translation, correction, reordering or automatic summary. A minimal navigation wrapper/embed can be useful but is not itself the original payload.
- Both modes retain provenance, guarded writes, review boundaries, source ownership and supported cleanup. Do not duplicate the transaction engine.
- Do not create a low-value canonical page merely to satisfy cleanup. If a source-only record or wrapper fails the existing guard, retain staging and report the limitation.
- Raw search coverage is not automatic: distinguish discoverable wrapper text from indexed source body.

When asked to send current and proposed skills, export byte-identical current SKILL.md files and their relevant references, draft alternatives outside the live skills directory, include a comparison/routing/test proposal, and validate the review package. Clearly distinguish structural validation from runtime ingest tests. Snapshot hashes allow checking that active skills remained unchanged during preparation.

## Local installation versus repository

Read the supplied repository before claiming compatibility. Pin the review to a commit and compare content rules, adapter APIs, schema, cleanup policy and host guarantees. Repository docs may conflict internally or lag installed behavior. Report that as a baseline question rather than silently substituting an older implementation. Once the user identifies the intended baseline, revise only the proposal accordingly. Updating the repository, activating skills and changing scheduled jobs are separate authorizations.

For byte-preserving capture, failure on newline/BOM/encoding changes is an honest blocker. Never convert a mismatch to a success by replacing the original baseline hash with the output hash. Do not document an untested workaround as a proven capture path.
