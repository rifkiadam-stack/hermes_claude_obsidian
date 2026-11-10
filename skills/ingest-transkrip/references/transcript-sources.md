# Transcript-style sources

Reference for `ingest-transkrip`, used only after an explicit user command selects transcript mode and the source scope. Never select a mode from a folder, content or medium; cron uses verbatim only. YouTube is the primary use case; the same principles apply to podcasts, webinars, and meeting recordings. Technical lifecycle, provenance and unattended-operation rules are governed by the installed shared ingest core and setup registry.

## 1. Define the output and scope

- An edited note representing one source is an **enriched source summary**: a structured representation of that source with attribution and locators. It is not automatically a cross-source concept page or an independently established conclusion.
- This describes the page's content role, not a new frontmatter `type`. Use the schema, frontmatter, and addresses supported by the selected vault; do not introduce unsupported page types or ledger fields.
- Transcript mode was explicitly selected, so a summary page is expected. Check hashes and duplication first: a source already summarized with the same hash is a no-op. Do not automatically split one video into many pages either.
- Unattended ingest never merges material into an existing topic note or replaces an existing page. Create a new page and link it from the active MOC/index; merging is a separate explicit command.
- Set budgets for source size, reading, segments, drafts, and network access before processing. Do not silently reduce coverage to fit the budget.

## 2. Inventory and normalize a working copy

1. Record only available metadata: title, URL/video ID, channel, speaker, language, caption type (manual/automatic/unknown), upload date if available, and capture date. The channel is not necessarily the speaker. Do not invent metadata.
2. Preserve the original payload intact for create-only archival under `.raw/`. Keep working copies and temporary analysis artifacts outside the vault. Do not treat normalized text as a new raw source or overwrite the original.
3. In the working copy, parse VTT/SRT cues, remove presentation markup, and deduplicate rolling captions only when overlapping words and cue timing support that interpretation. Do not remove intentional repetition at different points in the talk.
4. Tags such as `[Music]`, `[Musik]`, or `[Applause]` may be excluded from the analysis text when they add no substance; preserve nonverbal context that affects meaning. Do not merge different speakers' statements under one attribution.
5. Normalize spacing and punctuation conservatively. Do not guess corrections to ambiguous names, numbers, terminology, or speech. Flag important unclear passages. Do not verify the normalized text against itself.
6. Retain a mapping from each working unit to its original cues/time range. For untimed text, use paragraph numbers or line ranges from the raw snapshot; never fabricate timestamps. Keep the snapshot hash with the working map so locators are reproducible.

Completion criteria: the original payload is intact; every working segment can be traced to the source; no substantive passage has been discarded as noise without a reason.

## 3. Handle long transcripts

- Before synthesis, inventory segments in source order. For long sources, start with topic boundaries or approximately 5–10-minute ranges, adjusting boundaries to avoid cutting an argument in half. For untimed text, use manageable paragraph/line groups. These are working heuristics, not permission to invent durations.
- For each segment, record start/end locators, speaker if known, central ideas, examples, qualifications, important claims, and ambiguities. A small overlap may preserve context; do not count it as additional content.
- Once all in-scope segments have been read, synthesize thematic notes from the segment records, then return to the raw source for details prone to error. Do not rely only on the introduction/conclusion or on summaries of summaries without source access.
- Every segment must be marked **represented**, **excluded with a reason** (for example, an advertisement), or **not yet processed**. Middle sections must not disappear silently.
- If the budget is insufficient to process every segment, do not draft: the source is held in staging and reported (partial summaries are not produced in this version). A finished draft may not contain any segment marked not yet processed.

## 4. Draft an enriched source summary

- Write the resulting note in Indonesian unless the user requests another language. Preserve important technical terms and source meaning, including negation, certainty, exceptions, and differing views. The skill's English instruction language does not change the requested output language.
- Organize around ideas and their relationships, not merely shortened caption cues. Retain explanations and examples needed for depth. Remove irrelevant filler, greetings, and promotions from the derivative note.
- Use a flexible default structure: **Core summary → Thematic discussion → Implications/reflection when relevant → Sources and limitations**. Do not force empty headings, fixed lengths, action items, or bullet counts.
- Distinguish the speaker's statements/opinions, examples/analogies, and agent synthesis. Additional claims from external sources require separate provenance and approved scope/egress.
- Verbatim quotations must match the raw source. Do not present edited working-copy text as original speech. Label translations; do not format paraphrases as verbatim quotations. Use genuine timestamps or paragraph/line locators.
- If interpretation depends on unavailable slides, demonstrations, code, or charts, state the transcript's limitations. Do not claim to have watched the video or inspected visual material.
- Select destinations only from enabled, user-approved topic routes in the setup registry. Hold and report unmapped or ambiguous topics. Do not create folders or MOCs because of the medium. Link new pages from the registered existing active index/MOC.

## 5. Verify and produce a coverage map

Verification must finish **before apply**, but is not independent fact-checking.

### A. Mechanical checks

Use `terminal` with standard-library Python or an actually available read-only helper to match draft candidates against the raw source. Working files remain outside the vault. This reference does not assume a new helper has already been installed.

- Inventory draft numbers with their units/context, important names, quotations, and timestamps. Report matching candidates, nonmatches, and candidates needing manual review.
- Match verbatim quotations against the raw source using explicitly declared whitespace normalization. Do not disguise changed punctuation/spelling as an exact match. Confirm timestamps exist or fall within actual cue ranges and point to passages supporting the relevant claim.
- Literal matching of numbers and names is only a signal. A translation or conversion such as `1.5 billion` to `1,5 miliar` may be valid after explicitly mapping units, context, and source evidence. Do not reject a candidate solely because literal matching fails, or accept it merely because the same token appears elsewhere.
- These checks do not establish correct attribution, causality, or completeness. Semantic review is still required. If a blocker prevents mechanical checks, report **not performed**, not PASS.

### B. Semantic review and a separate verifier

Compare source and draft for meaning, negation, causality, attribution, exceptions, certainty, and coverage. Revise unsupported or miscontextualized claims and analogies turned into literal facts.

For every transcript, require a separate verifier through `delegate_task`, with actual tool-availability evidence recorded for A10 and a completed source-specific review. Supply the source, draft, and scope/locators—not a conclusion that the draft is already correct. The verifier returns findings and evidence only; it must not mutate the vault or access the network outside approved scope. The orchestrator resolves findings before apply. If the verifier is unavailable or incomplete, hold the transcript before any mutation and report it; never substitute self-review.

### C. Required preview evidence

Show an actual coverage map, not an empty template:

| Note section | Source locator | Support status | Uncertainty/action |
|---|---|---|---|

- Map each substantive section and key claim to one or more raw timestamp/paragraph/line ranges.
- Include the source-segment inventory: represented, excluded with a reason, or not yet processed. The map must demonstrate source-to-draft coverage, not only draft-to-source support.
- Include mechanical-check results, semantic findings, separate-verifier status, and unresolved issues. The map/report may be attached as preview artifacts outside the vault; do not automatically create extra wiki pages for them.
- Unresolved material errors block applying the draft; the source is held in staging and reported. Partial results are never applied in this version.

There is no human approval step. "Preview" here means the orchestrator's own pre-apply evidence; the shared core's automatic scope check and the guarded inspect/execute lifecycle decide whether the operation may run, and the coverage map is attached to the final report.

## 6. Keep provenance and ledgers proportionate

- Store source identity/provenance in the source ledger and claim assessments in the claim ledger. Do not add every transcript sentence to the claim ledger: select key falsifiable claims relevant to the note's conclusions. Attribute opinions, advice, analogies, and minor details in the summary when they do not need a separate assessment.
- A speaker's name is attribution, not an `authority` value. Use only supported source-authority values: `official`, `primary`, `secondary`, `community`, `synthetic`, `unknown`. Choose based on the source's relationship to the claim: a speaker is a primary source for their own statement/experience, not automatically for external facts they cite.
- Caption type describes extraction quality. Automatic captions warrant closer checks of names/numbers/quotations, but manual captions do not establish factual correctness. Record this information in supported metadata or the sources/limitations section; do not invent schema fields.
- Source review states remain `unreviewed`, `active`, `superseded`, or `rejected`; claim assessments remain `accepted`, `provisional`, `contested`, `unsupported`, or `deprecated`, under the provenance contract. Do not promote status solely because summarization or literal matching passed.
- Captions, transcripts, and the corresponding video share an origin/independence key; they are not independent corroboration. High-risk claims still require independent support under the existing rules.

## 7. Return to the shared lifecycle

Once the draft and verification evidence are ready, continue with the shared core: automatic scope check, one guarded ingest operation, raw/hash/ledger/navigation checks, lint, scoped cleanup, index and final report. Do not change original sources, guards, schemas, or vault configuration as a side effect of the transcript workflow.
