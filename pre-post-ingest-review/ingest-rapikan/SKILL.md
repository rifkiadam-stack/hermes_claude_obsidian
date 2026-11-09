---
name: ingest-rapikan
description: "Tidy text notes while retaining every source point."
version: 0.3.4
author: Rifki Rahmazaki Adam, Hermes Agent
license: MIT
platforms: [windows]
metadata:
  hermes:
    tags: [second-brain, obsidian, ingest, notes]
    related_skills: [ingest-verbatim, ingest-transkrip, second-brain-native-windows, wiki-lint]
---

# Ingest rapikan

## When to use

Use only for `ingest rapikan clipping`, `ingest rapikan inbox`, `ingest rapikan chat ini` or `ingest rapikan` with same-request supplied files/text. Tidy structure, order, paragraphing and grammar while keeping **every point**; this is not a summary. Messy formatting or folder placement never activates it. Without scope/inputs, do no work and report missing scope. Reject rapikan cron jobs; cron is verbatim only.

## Prerequisites and loading

Read the setup-registered absolute `INGEST_REGISTRY_PATH` with `read_file`, then its setup-registered `INGEST_CORE_PATH` with `read_file`. Require a supported registry version `3.3` or `3.4` with the matching version-specific contract, approved policy values, approved enabled domain routing, concrete setup values and execution-backed `proven`/`PASS` capability records. For 3.4 require the exact `content-retention` profile; for 3.3 preserve the legacy contract. Missing, conflicting, ambiguous or unavailable values => hold/report without questions, preview or approval prompts. Do not guess paths, use loader traversal or create configuration.

For registry 3.4 require common gates **A1, A2, A3, A4, A5R, A6, A7, A8**; for registry 3.3 retain **A1, A2, A3, A4, A5a, A6, A7, A8**. Require applicable acquisition evidence in either version. Treat this skill and core as a contract, not a working engine. Do not substitute generic file writes for native guards. Use only existing `inbox/` and `Clippings/`; modes come from commands only. Follow the core for original authority, actual-state recovery, immutable raw, destination routing, exact preconditions, scope checks, proof-bound cleanup, lint and lifecycle reporting.

## Content procedure

1. Freeze full source bytes/hash and validate admissibility/budget. Preserve immutable raw through the core. Hold incomplete/oversized input whole, without partial output.
2. Split the source into stable units with raw line/paragraph locators: assertions, examples, qualifications, questions, numbers/units, quotations, action items, owners/deadlines, links and conflicting views. Timestamps are content, not a mode signal.
3. Reorganize headings, order, paragraphs, grammar and list style. Keep original language unless translation is explicitly requested; retain technical terms, claim strength, negation, attribution and exceptions.
4. Do not drop repetitions as filler, remove examples, merge distinct views, resolve contradictions, infer missing conclusions or add facts. Overlapping units may share a sentence only if every nuance survives and both are mapped; when uncertain, retain both.
5. Keep ambiguous names, numbers, abbreviations and quotations as written. List ambiguities in **Catatan penyunting** outside the tidied content; never silently repair them. Quotations remain exact.
6. Label the page **Catatan dirapikan — seluruh poin dipertahankan; bukan ringkasan** and include the independently valid standalone archive proof.
7. Build full bidirectional coverage: every source unit → output location, every substantive output statement → source units. Missing source destination or unsupported output => hold with failing units identified. Counts/token overlap are not coverage proof. A separate read-only review may add evidence if available; do not mislabel self-review as independent. A10 is mandatory for transkrip, not this mode.
8. Apply only the exact inspected, scope-checked native operation and complete readback, lint, separate allowlist cleanup and retrieval under the core. An apply failure or drift stops the run with actual recovery authority preserved.

## Pitfalls

`ringkas` or a shortening request is unsupported: hold/report, do not silently summarize. Notes resembling captions still follow rapikan rules. Similar-topic pages authorize no merges or edits. Missing/unapproved domain route holds the source; do not guess a fallback or create folders. Never perform setup/cron/skill changes during ingest.

## Verification and closing report

Require baseline/raw/ledger/manifest equality, complete bidirectional unit coverage, retained numbers/units and attributed views, no inferred facts or silent corrections, applied output matching the checked candidate, valid generated YAML/proof/MOC and native lifecycle evidence. Deliver one Indonesian closing report with exact scope, change summary, content state, coverage and lint/cleanup/index outcome. Ask no runtime questions; report holds without pretending content was untouched after commit.


## Local installation bindings

This installation resolves `INGEST_REGISTRY_PATH` to `C:/Users/rahmazaki.adam/AppData/Local/hermes/components/claude-obsidian-ingest-v34/setup-registry.json` and `INGEST_CORE_PATH` to `C:/Users/rahmazaki.adam/AppData/Local/hermes/skills/second-brain/_shared/ingest-core.md`. Read those exact files before execution. These are installed-location bindings only; they do not approve activation, routes, or capability gates. A disabled or unproven registry must HOLD without falling back to the legacy ingest writer.
