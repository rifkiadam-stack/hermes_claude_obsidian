# Asset rename workflow

## Scope

Use this reference when renaming Obsidian vault images so names explain which Markdown page uses them.

## Audit before rename

1. Enumerate image files in `assets/` by extension.
2. Scan every `wiki/**/*.md` file for each exact asset basename, covering both Obsidian embeds (`![[name.png]]`) and Markdown paths.
3. Partition assets into:
   - referenced exactly once: safe candidates for page-derived names;
   - referenced by multiple pages: do not blindly name after one page; choose a shared name or leave unchanged;
   - unreferenced: report only, do not rename automatically.
4. Confirm no duplicate target names and preserve original extensions.

## Naming

For a single-reference image, derive a filesystem-safe slug from the Markdown basename and append a 1-based counter per source page:

`<markdown-slug>_1.png`, `<markdown-slug>_2.png`

Use the original extension and deterministic ordering (for example, current asset filename sort or first-reference order). Avoid changing `.raw/`; raw is immutable source archive, while `assets/` is presentation material.

## Transaction and verification

Rename operations are vault mutations and must use one write-guard bundle:

- write each new asset path with byte-identical content;
- update every referencing Markdown file from old basename/path to new basename/path;
- remove old asset paths only through the transaction mechanism supported by the selected core, never direct filesystem deletion;
- include any required asset manifest/log updates in the same logical operation.

Before apply, record expected hashes and inspect the approval hash. After apply:

- verify every new asset hash equals its old asset hash;
- verify zero missing image references via lint/reference scan;
- verify old names no longer occur in `wiki/**/*.md` or active asset manifests;
- verify the count of referenced images is unchanged;
- report unreferenced images separately instead of treating them as rename failures.
