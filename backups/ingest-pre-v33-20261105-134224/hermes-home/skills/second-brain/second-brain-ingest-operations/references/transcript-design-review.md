# Reviewing transcript-ingest extensions

Use when comparing proposed changes to `wiki-ingest` or reviewing a transcript-derived draft. Do not install a user-uploaded draft unless installation is explicitly authorized. Keep the portable user-owned skill untouched during autonomous curation.

## Architecture and scope checks

- A single-video enriched source summary is not automatically a canonical topic page. State its role before assembling the transaction. Preserve the compilation-value gate, duplicate/no-op behavior, and explicit review for canonical replacements; avoid a mandatory new page for every video.
- Keep `SKILL.md` to a short trigger and core invariants; detailed transcript processing belongs in a conditional reference. Religious-source guidance can be a separate reference loaded only when applicable. Require referenced files to exist before treating a package as complete.
- Trigger from actual content and provenance, not URL/extension alone: WEBVTT, timestamp patterns, rolling repeated lines, stage tags, and spoken prose are useful signals, not individual proof. Already-organized notes should not be rewritten just because their source was YouTube. The same source class includes podcasts, webinars, and meeting transcripts; retain speaker attribution and distinguish discussion from decisions.
- Existing supplied transcript text is ordinary readable text. Obtaining a transcript from audio/video is a separate extraction capability and egress decision.
- Destination paths and topical routing belong in vault-local methodology/configuration. 'Do not create a new MOC' still permits and requires applicable updates to an existing active index/MOC.

## Source fidelity and long-input review

- Preserve raw payload bytes create-only. Remove rolling-caption noise only in a temporary working representation; do not silently replace the original with normalized text or create unnecessary intermediate vault pages.
- For long sources, require explicit segment coverage: stable timestamp ranges or paragraph/cue IDs, segment evidence notes, then thematic synthesis. Do not claim full coverage merely from a successful transaction or a fluent summary. Label omissions and partial extraction honestly.
- A useful preview coverage map is `draft section → source time/paragraph range → support status → uncertainty`. Source locators must really exist; never invent timestamps for untimestamped prose.
- Literal checks can flag unmatched names, numbers, timestamps, and quotations. They are not semantic verification: legitimate translations, paraphrases, spelling variants, and number-format changes may not match literally, while a matching token can appear in the wrong context. Investigate flags rather than automatically rejecting them or accepting all matched claims.
- Verbatim quotations and timestamps deserve strict checks. Separately review negation, causal links, speaker attribution, uncertainty, exceptions, and whether examples/analogies became literal claims.
- A separate verifier supplied only source and draft can reduce drafting bias, but is not independent factual corroboration. Do not describe proposed helper scripts or verifier flows as tested until exercised on real/fixture inputs with reported results.

## Provenance and ledger constraints

- Consult the live provenance contract before writing records. Supported source authority values are `official`, `primary`, `secondary`, `community`, `synthetic`, `unknown`; a speaker's name is attribution, not an authority enum.
- Review states are `unreviewed`, `active`, `superseded`, `rejected`; claim assessments are `accepted`, `provisional`, `contested`, `unsupported`, `deprecated`. Do not invent fields or values without reviewing schema support.
- Source authority is relative to the assertion: a speaker can be primary for what they said or experienced, not automatically for every historical/scientific/religious claim they repeat.
- Manual versus automatic captions describe extraction quality, not factual truth or automatic acceptance. Video and its captions are representations of one source, not independent corroboration.
- Avoid a claim record for every utterance. Select key falsifiable claims relevant to the note and authorized assessment scope; keep explanation, opinion, and examples attributed in prose. Do not silently expand an ingest into exhaustive fact-checking.
- Religious-source reviews must distinguish speaker interpretation, scripture/hadith quotations, disputed views, and agent synthesis. Never infer Arabic wording, verse numbering, hadith source/authenticity, or consensus from ambiguous captions.

## Acceptance checklist for a proposed package

1. Main skill, every referenced file, and any helper/template are supplied and consistent.
2. Existing transaction, archive, approval, and cleanup invariants remain intact.
3. Source-summary/canonical roles and no-op behavior are explicit.
4. Long-input coverage and pre-apply fidelity evidence are reviewable.
5. Verification does not overclaim independent truth checking.
6. Portable rules contain no incidental user/vault paths.
7. No new runtime behavior is claimed deployed or tested merely because a proposal document exists.
