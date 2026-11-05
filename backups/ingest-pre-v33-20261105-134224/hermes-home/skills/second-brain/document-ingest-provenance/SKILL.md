---
name: document-ingest-provenance
description: Use for mixed document ingestion with provenance.
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [windows]
metadata:
  hermes:
    tags: [ingest, provenance, documents, clipping, obsidian]
    related_skills: [wiki-ingest, second-brain-native-windows, wiki-lint]
---

# Document ingest with provenance

## When to Use

Use this skill when a user supplies mixed local documents—especially authored Markdown plus supporting PDFs/slides—and requests a concise canonical note with durable archive and provenance.

Use this skill when a user supplies one or more local documents and asks for a concise canonical Markdown note plus durable archive/provenance. It is especially useful for a user-authored Markdown note accompanied by slide decks, PDFs, or reference material.

## Core rule: distinguish authored notes from supporting sources

Classify every input before drafting:

- **User-authored note:** preserve all substantive content in the canonical page. Do not omit definitions, examples, analogies, formulas, prompts, caveats, personal observations, or selection rules merely to make the result concise. Clarify typos or elaborate shorthand when helpful, but preserve the author's meaning.
- **Supporting document/reference:** summarize selectively according to the user's requested level of detail. Do not imply that a concise summary is a full transcription.
- **Binary source:** extract it with a real document tool before summarizing. Archive the produced extracted text only when it was actually generated; never claim the binary itself was copied if the transaction contains only extracted text.

If the user later says that omissions are acceptable only for supporting PDFs, revise the canonical page so the authored Markdown is complete while the PDF sections remain deliberately selective.

## Workflow

1. Inventory every input, classify it, and read each in scope completely within a bounded budget.
2. Compute source hashes before drafting. Check the existing `.raw/.manifest.json` and source ledger to avoid duplicate ingestion.
3. Read the relevant existing MOC/index/hot-cache pages and choose one stable canonical address per logical note.
4. Draft the canonical page with complete authored-note sections first. Add a clearly labeled selective summary for supporting sources.
5. Preserve external image/video URLs as URLs unless download is explicitly requested. Do not fetch remote assets silently.
6. Build one guarded ingest transaction containing create-only raw captures, canonical page changes, ledger/manifest records, active MOC/index updates, one log entry, and hot-cache update as appropriate.
7. On native Windows, use the reviewed `hermes_windows_write` reduced-guarantee lifecycle: `inspect_operation` → review approval hash → `execute_operation`. Never write vault targets directly with generic file tools.
8. Read back the post-apply raw bytes. Native Windows writes may normalize line endings, so reconcile ledger/manifest hashes to the actual durable raw bytes in a second guarded operation if needed.
9. Run lint and distinguish new findings from pre-existing findings. Require zero new provenance/read/frontmatter regressions.
10. Run a separate guarded cleanup for direct children of `Clippings/` or `inbox/` only after raw, page, ledger, manifest, and lint verification. Never delete `.raw` or `.gitkeep`.
11. Verify cleanup, lock release, canonical page existence, and raw/ledger/manifest hash equality. Remove only temporary staging artifacts created for the operation.

## Quality checks

Before reporting success, confirm:

- every intended source is represented in the ledger and manifest;
- authored-note coverage includes its original headings and examples;
- selective PDF summaries are labeled as summaries;
- raw archive is create-only and hash-linked;
- external assets were not silently downloaded;
- `write.lock` is released;
- cleanup did not target unrelated staging files;
- lint has no new findings.

## Supporting detail

See `references/authored-notes-and-supporting-pdfs.md` for the preservation rule and a reusable review checklist.
