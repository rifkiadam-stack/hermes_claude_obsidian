# Authored notes and supporting PDFs

## Preservation checklist

Before apply, compare the canonical draft against the authored Markdown and check every original heading, definition, example, analogy, formula, prompt, caveat, and selection rule. Rewriting for clarity is allowed; silent omission is not.

## Mixed-source rule

Label the authored-note section as complete or substantially complete. Label PDF/slide sections as selective summaries when the user permits omission. Keep each source separately linked in `.raw/`, the source ledger, and `.raw/.manifest.json`.

## Binary provenance

If a PDF is extracted to text, record the extractor and archive only the text that was actually produced. Do not claim the PDF binary was archived unless the transaction contains the binary bytes. Preserve source cache locators in working evidence only when a durable vault-relative raw capture also exists.

## Final review

- authored content coverage reviewed;
- supporting-document omissions are intentional and labeled;
- raw hashes match ledger and manifest after native Windows read-back;
- no new lint or provenance findings;
- staging cleanup targets only the verified direct child source.
