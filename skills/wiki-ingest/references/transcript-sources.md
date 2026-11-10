# Transcript-style sources

Conditional reference for `wiki-ingest`. YouTube is the primary use case; the same principles apply to podcasts, webinars, and meeting recordings. This is not a separate skill and does not replace existing provenance, transaction, or approval contracts.

## 1. Define the output and scope

- An edited note representing one source is an **enriched source summary**: a structured representation of that source with attribution and locators. It is not automatically a cross-source concept page or an independently established conclusion.
- This describes the page's content role, not a new frontmatter `type`. Use the schema, frontmatter, and addresses supported by the selected vault; do not introduce unsupported page types or ledger fields.
- A page is not mandatory for every video. Check hashes, duplication, existing notes, and the compilation-value gate. A source with no additional value may produce only a source/ledger record or a no-op under the existing workflow. Do not automatically split one video into many pages either.
- Creating or expanding a canonical page remains subject to the compilation-value gate. Merging material into an existing topic note is a canonical replacement and requires review before apply.
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
- If the budget is insufficient, process a clearly bounded tranche, identify the unprocessed ranges, and label the result partial. Do not claim to summarize the entire episode.

## 4. Draft an enriched source summary

- Write the resulting note in Indonesian unless the user requests another language. Preserve important technical terms and source meaning, including negation, certainty, exceptions, and differing views. The skill's English instruction language does not change the requested output language.
- Organize around ideas and their relationships, not merely shortened caption cues. Retain explanations and examples needed for depth. Remove irrelevant filler, greetings, and promotions from the derivative note.
- Use a flexible default structure: **Core summary → Thematic discussion → Implications/reflection when relevant → Sources and limitations**. Do not force empty headings, fixed lengths, action items, or bullet counts.
- Distinguish the speaker's statements/opinions, examples/analogies, and agent synthesis. Additional claims from external sources require separate provenance and approved scope/egress.
- Verbatim quotations must match the raw source. Do not present edited working-copy text as original speech. Label translations; do not format paraphrases as verbatim quotations. Use genuine timestamps or paragraph/line locators.
- If interpretation depends on unavailable slides, demonstrations, code, or charts, state the transcript's limitations. Do not claim to have watched the video or inspected visual material.
- Select destinations using active methodology settings and existing navigation. Do not create folders or MOCs because of the medium. Link new pages from an existing active index/MOC; canonical-page navigation requirements still apply.

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

For long/multisegment transcripts, complex attribution, or high-risk claims, prefer a separate verifier through `delegate_task` when available. Supply the source, draft, and scope/locators—not a conclusion that the draft is already correct. The verifier returns findings and evidence only; it must not mutate the vault or access the network outside approved scope. The orchestrator resolves findings before apply. If a separate verifier is unavailable, disclose that the same agent performed the review; do not claim separate verification.

### C. Required preview evidence

Show an actual coverage map, not an empty template:

| Note section | Source locator | Support status | Uncertainty/action |
|---|---|---|---|

- Map each substantive section and key claim to one or more raw timestamp/paragraph/line ranges.
- Include the source-segment inventory: represented, excluded with a reason, or not yet processed. The map must demonstrate source-to-draft coverage, not only draft-to-source support.
- Include mechanical-check results, semantic findings, separate-verifier status, and unresolved issues. The map/report may be attached as preview artifacts outside the vault; do not automatically create extra wiki pages for them.
- Unresolved material errors block applying the draft as if it were complete. A partial result may proceed only with explicit limitations/ranges and the applicable scope approval.

This introduces no universal extra manual-approval step for every video. Review of canonical replacements, scope expansion, and other approvals continues under the main skill.

## 6. Keep provenance and ledgers proportionate

- Store source identity/provenance in the source ledger and claim assessments in the claim ledger. Do not add every transcript sentence to the claim ledger: select key falsifiable claims relevant to the note's conclusions. Attribute opinions, advice, analogies, and minor details in the summary when they do not need a separate assessment.
- A speaker's name is attribution, not an `authority` value. Use only supported source-authority values: `official`, `primary`, `secondary`, `community`, `synthetic`, `unknown`. Choose based on the source's relationship to the claim: a speaker is a primary source for their own statement/experience, not automatically for external facts they cite.
- Caption type describes extraction quality. Automatic captions warrant closer checks of names/numbers/quotations, but manual captions do not establish factual correctness. Record this information in supported metadata or the sources/limitations section; do not invent schema fields.
- Source review states remain `unreviewed`, `active`, `superseded`, or `rejected`; claim assessments remain `accepted`, `provisional`, `contested`, `unsupported`, or `deprecated`, under the provenance contract. Do not promote status solely because summarization or literal matching passed.
- Captions, transcripts, and the corresponding video share an origin/independence key; they are not independent corroboration. High-risk claims still require independent support under the existing rules.

## 7. Continue the existing lifecycle

Once the draft and verification evidence are ready, continue with preview, required review, one guarded ingest operation, raw/hash/ledger/navigation checks, lint, and verified staging cleanup. Do not change original sources, guards, schemas, or vault configuration as a side effect of the transcript workflow.
