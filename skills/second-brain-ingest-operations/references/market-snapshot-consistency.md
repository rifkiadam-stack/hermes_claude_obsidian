# Market snapshot and arithmetic distinctions

Use during ordinary source-fidelity checking of a bundled Market Highlights + later daily update. These checks do not authorize external research or a separate review project.

## Classify repeated observations before calling them conflicts

- **Forecast versus decision:** a morning forecast that a central bank will raise rates and a later report that it held rates are expectation/outcome observations. Preserve both with their source-block labels. Do not erase the forecast or describe it as an erroneous actual decision.
- **MTD versus peak-to-current:** a reported monthly yield decline and the difference between an intramonth peak and the latest yield have different baselines. Calculate the latter separately if useful, label its basis, and do not replace MTD with it. When the month-start level is absent, do not reconstruct it. A source sentence conflating these bases deserves an explicit uncertainty note, not a silently repaired number.
- **Approximate versus precise:** an inventory decline quoted as roughly 2 million barrels and later as 2.031 million may be differently rounded accounts of one observation. Preserve precision and labels; do not count them as independent corroboration or assume they conflict.
- **Snapshot versus close:** identify the same instrument, units, source section, and stated time before comparing values. A heading date is not the observation time of every quote in that section. Preserve later and earlier values separately; do not invent missing timestamps.
- **Different capital-flow windows:** stock flows may end today while bond flows end on the prior trading day. Keep the exact start/end labels. Daily PLTE, post-event, MTD, and YTD flows are not automatically reconcilable series. Do not subtract a PLTE foreign net buy from cumulative inflow or infer a missing daily flow from their difference without matching coverage and definitions.
- **Pending versus completed policy event:** retain terms such as expected, probability, and hawkish hold when the source precedes an FOMC announcement. Do not turn a stated hold expectation into an actual decision or interpret a parenthetical policy rate beside an upcoming meeting as a newly announced outcome.
- **Ambiguous market measure:** when a source says a bond 'fell' but supplies bps and a percent level, preserve that wording/units and flag the likely yield interpretation as interpretation if needed. Do not silently convert it into a claim about bond prices. Likewise, do not add a benchmark identity absent from the source.
- **Mixed wording/sign:** retain a label such as `outflow Rp-X T` exactly. In synthesis, explain that the sign and label are supplied by the source; do not reinterpret it as inflow or silently remove the minus.

## Mechanical checks

Use Decimal arithmetic rather than floating-point comparisons for displayed yield percentages: `(after - before) * 100` yields bps. Preserve all three source fields: before, after, reported bps. Put differences in a consistency note, not corrected table cells. Reported direction remains the summary basis; if computed direction differs, explain both counts separately.

Calculate index/FX point changes independently and distinguish a rounding match (for example, a displayed gain of 16.18 reported as 16 points) from a material mismatch. Do not infer missing precision as the cause of a mismatch; say that higher-precision source data or the cause is unavailable.

## Verification boundary

Raw-byte/hash equality, stable source identity, manifest/page linkage, lint, and BM25 retrieval establish preservation and operation integrity—not truth of market, corporate, political, or policy claims. Keep the source unreviewed and avoid introducing accepted claim assessments without the required independent support. Retrieval may rank the correct page using a later chunk; check `page_path`, not whether `chunk_index` equals zero.
