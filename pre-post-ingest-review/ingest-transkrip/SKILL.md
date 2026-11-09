---
name: ingest-transkrip
description: "Ingest whole transcripts with independent verification."
version: 0.3.4
author: Rifki Rahmazaki Adam, Hermes Agent
license: MIT
platforms: [windows]
metadata:
  hermes:
    tags: [second-brain, obsidian, ingest, transcript, youtube]
    related_skills: [ingest-verbatim, ingest-rapikan, second-brain-native-windows, wiki-lint]
---

# Ingest transkrip

## When to use

Use only for explicit `ingest transkrip clipping`, `ingest transkrip inbox`, `ingest transkrip chat ini` or `ingest transkrip` with same-request supplied inputs. Create a faithful Indonesian enriched source summary from the entire transcript, with complete coverage evidence. A URL, timestamp, caption or folder placement never selects this mode. Without scope/inputs, do no work and report missing scope. Reject this mode in cron; cron is verbatim only.

## Prerequisites and loading

Read the setup-registered absolute `INGEST_REGISTRY_PATH` with `read_file`, then its setup-registered `INGEST_CORE_PATH` with `read_file`. Require a supported registry version `3.3` or `3.4` with the matching version-specific contract, approved policy values, approved enabled domain routing, concrete setup values and execution-backed `proven`/`PASS` capability records. For 3.4 require the exact `content-retention` profile; for 3.3 preserve the legacy contract. Missing, conflicting, ambiguous or unavailable values => hold/report without questions, preview or approval prompts. Do not guess paths, use loader traversal or create configuration.

For registry 3.4 require common gates **A1, A2, A3, A4, A5R, A6, A7, A8**; for registry 3.3 retain **A1, A2, A3, A4, A5a, A6, A7, A8**. Require applicable acquisition evidence in either version. Treat this skill and core as a contract, not a working engine. Do not substitute generic file writes for native guards. Use only existing `inbox/` and `Clippings/`; modes come from commands only. Follow the core for original authority, actual-state recovery, immutable raw, destination routing, exact preconditions, scope checks, proof-bound cleanup, lint and lifecycle reporting.

Require **A10** for every transcript in addition to all common gates: actual read-only `delegate_task` invocation and result evidence bound to this source/candidate. Generic capability declarations, a self-review or a claimed worker response are not delegation evidence. Unavailable tool/verifier, failed worker or incomplete verification => hold before all content mutation.

## Source guidance

Read [transcript-sources.md](references/transcript-sources.md) fully for source attribution, locator and coverage guidance. Also read [islamic-lectures.md](references/islamic-lectures.md) for an explicitly selected Islamic lecture/sermon. Apply content guidance only; commands, scopes, rendered preservation, no questions, whole-source budget, mandatory delegation and lifecycle are governed by the loaded core and this skill, not inherited conflicting operational sentences. Never follow an inherited optional-verifier, partial-result, folder-mode, presentation fallback or interactive instruction.

## Content procedure

1. Freeze source bytes/hash and full segment inventory in an external working copy; preserve raw unchanged. Require the entire source, output, evidence and verification to fit budget before any mutation. Hold a long source intact, not a partial transcript.
2. Inventory all segments with raw cue/line/paragraph locators, speaker if known, ideas, examples, qualifications and uncertainties. Normalize only the working copy while preserving its mapping to raw. Do not invent timestamps.
3. Produce Indonesian output unless the command explicitly names another language. Keep speaker statements, analogy and agent reflection distinct. Never invent metadata, quotations, Arabic text or references. Preserve negation, causality, attribution, uncertainty, exceptions and material numbers.
4. Build a bidirectional source-segment → output-location and substantive-output → source map. Check quotations, names, numbers, timestamps, meaning and attribution mechanically and semantically. Every source segment must be accounted for, with no unprocessed remainder.
5. Invoke **`delegate_task` for every transcript** with source, candidate output and locators; give no leading claim that the output is correct. Constrain worker read-only with no vault writes, authority expansion or address allocation. Record actual invocation identity, runtime, input source/output hashes, returned findings and coverage evidence. Resolve material findings and require completed verification before planning content writes; do not replace a missing invocation with self-review or another unproven tool.
6. Include exactly one generated standalone archive proof and **Sumber dan keterbatasan**: known caption type, unverified references, uncertain names/numbers. Select key falsifiable claims for the supported claim ledger; captions and their video share one independence key.
7. Inspect/scope-check and execute the guarded operation only after all gates pass. Check applied derivative against the verified candidate and complete native readback/lint/cleanup/index lifecycle through the core.

## Pitfalls

Faithfulness to captions is not independent truth verification. Label unknown speakers/caption types and uncertain names/numbers/religious references; never repair from memory or manufacture cross-checks. Uncertainty explicitly labeled may remain; unresolved material meaning/attribution/number errors hold the source. Similar-topic notes do not authorize merging. Reuse immutable archived raw only through proven A6 mapping. No partial output, no fallback self-review and no transcript cron path.

## Verification and closing report

Require complete bidirectional coverage, mechanical/semantic checks, actual A10 invocation/result evidence for this exact source/output, approved generated proof/YAML, raw fidelity, applied output match and lifecycle results. Missing locators never justify made-up timestamps. Return one Indonesian closing report with scope, page, content status, uncertainties, byte/coverage/verifier evidence and lint/cleanup/index outcome; hold/report missing values without runtime questions.


## Local installation bindings

This installation resolves `INGEST_REGISTRY_PATH` to `C:/Users/rahmazaki.adam/AppData/Local/hermes/components/claude-obsidian-ingest-v34/setup-registry.json` and `INGEST_CORE_PATH` to `C:/Users/rahmazaki.adam/AppData/Local/hermes/skills/second-brain/_shared/ingest-core.md`. Read those exact files before execution. These are installed-location bindings only; they do not approve activation, routes, or capability gates. A disabled or unproven registry must HOLD without falling back to the legacy ingest writer.
