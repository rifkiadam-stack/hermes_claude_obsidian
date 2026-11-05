# Ingest fidelity, routing, and selective cleanup

Use with the main clipping workflow. This reference supplements, but does not replace, the user-owned `wiki-ingest` rules or the native Windows transaction contract.

## Faithful summaries without an unsolicited audit

The verification target is whether the derivative note represents the supplied source accurately. This is part of ingest, not an automatic invitation to investigate the author's claims or review the user's code, configuration, or workflow.

- Distinguish source assertions from editor synthesis. If the author makes a categorical prediction, preserve that attribution; do not quietly rewrite it as a cautious heuristic. Put the caveat in a separately labeled editor's note.
- Do not euphemize a materially relevant admission. If the source explicitly describes deceiving another agent about possessing ground truth, state that this is what the author reports, without adopting the tactic as an instruction to the ingest agent.
- Preserve the scope of prohibitions and qualifications. Do not add a motive-based exception to an unconditional source statement, or remove a source exception merely to make the prose smoother.
- Source examples, rhetoric, classroom anecdotes, motivational generalizations, and reported success rates are not independently established facts. Attribute them and avoid upgrading their provenance assessment after a successful paraphrase check.
- Keep the original payload create-only and intact. Correct derivative wording through the guarded lifecycle, never by editing the raw source.

A separate verifier is optional unless the governing workflow or user explicitly requires it. If used, obtain and resolve its findings before apply/completion. Another agent checking the same source is not independent corroboration or religious authentication. Do not use delayed verifier results as a routine post-completion editing phase.

## Transcript-specific evidence

Load `wiki-ingest`'s transcript and Islamic-lecture references when applicable. Preserve these distinctions:

- A supplied Markdown transcript is readable source text; acquiring/transcribing audio or video is a different capability and egress decision.
- Maintain raw-line/timestamp mappings while normalizing a working copy outside the vault. Do not repair ambiguous Arabic, names, verse numbers, or references from memory.
- A range from the first cue's start to the last cue's start describes available cues, not the original video's full duration or the end of the final spoken passage. An offset in a video URL does not prove the clipping contains only that offset's excerpt.
- Use source segments and a note-to-source coverage map. Check every draft timestamp against actual source cues; validate meaning and attribution separately from literal matching.
- Caption type remains unknown if the capture does not identify it. Visible caption errors do not establish whether the captions were automatic or manual.
- Describe the generated page as an enriched source summary when representing one lecture. This is a content role, not a new frontmatter or ledger enum. No page is mandatory for a duplicate or low-value source; canonical expansion and merging remain subject to the existing gate and review rules.

## Routing and navigation

Use the user's requested existing area. A new lecture note is different from a new category note or MOC. Reuse the existing active index/MOC and update its links in the same guarded ingest operation. Do not interpret “put this in reflection” as permission to scaffold a new hierarchy.

When a user deletes an unnecessary category page and asks for cleanup, inspect the current vault first. Remove the stale navigation references and obsolete hot-cache link, preserve historical log entries, and add a corrective operation entry. Do not recreate or delete another page on their behalf. Verify that the removed page remains absent and that lint has no broken links introduced by cleanup.

## Provenance schema details

- For a local Markdown clipping, use the supported `content_kind: document` and a stable source ID derived from the exact raw locator and content hash.
- `source-ledger.sources[ID].ingested_at` is an ISO date (`YYYY-MM-DD`), not a full UTC timestamp. Keep a generated timestamp in a field that actually accepts timestamps, such as ledger `generated_at`.
- A speaker's name is attribution, not a source-authority enum. Respect the provenance contract's supported authority and review-state values.
- Compute hashes from original source bytes. Check the actual archived bytes after apply and ensure the ledger and manifest describe those same bytes.
- Keep the exact standalone archive link required by staging cleanup, such as `Sumber arsip: [[.raw/exact filename.md]]`. General source links or a frontmatter list alone do not prove the cleanup chain.

## Scope-safe staging cleanup

The discovery adapter may inspect both `inbox/` and `Clippings/`, even when the user authorized only one clipping. Its global results are an inventory, not permission to delete every eligible file.

1. Select only the exact requested direct-child staging paths.
2. Require a complete provenance chain for each selected path. A blocked selected target stays in staging and is reported; never filter away its failure to force cleanup.
3. Preserve unrelated targets, including blocked inbox assets and other verified files outside the requested batch.
4. Bind selected staging hashes plus ledger, manifest, raw, and note proof hashes to a separate inspected native guard operation. Its `deletes` array must contain only the authorized verified paths. Use the adapter's proof discovery rather than inventing a weaker delete test.
5. Execute through the guarded lifecycle. Check selected staging is absent, raw hashes still match, and `write.lock` is released. Never delete raw sources or `.gitkeep`.

If a broad cleanup CLI would include unrelated files, do not invoke it blindly. Construct a scoped guarded delete from the discovered complete proof for the selected batch.

## Completion checks

Re-run lint and compare to the baseline. Refresh BM25 through the native adapter, confirm stats changed when appropriate, exercise retrieval for the new note, and check stale candidates are zero. A no-change provisioning rerun should return its documented no-op status. Remove agent-created temporary source copies and helper scripts after verification; retain at most a useful completion/coverage report rather than a pile of raw duplicates.
