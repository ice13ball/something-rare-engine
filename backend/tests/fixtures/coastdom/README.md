# CoastDOM v1 fixture — attribution

`coastdom_slice.tsv` is the published PANGAEA textfile's full comment block and header
followed by **12 data rows copied byte for byte, except the PI e-mail cell, which is synthetic (`piN@example.org`) because this directory is published**, so the parser is tested against real
source bytes. `coastdom_meta.jsonld` keeps eight keys of the dataset's JSON-LD, values
verbatim.

**Source:** CoastDOM v1, PANGAEA, <https://doi.org/10.1594/PANGAEA.964012> — the full
citation is the `Citation:` line inside the slice's comment block.
**Licence:** CC-BY-4.0 — <https://creativecommons.org/licenses/by/4.0/>.

The slice keeps the whole file's `Size:` line (1,286,555 data points). Tests that need
the slice's own count substitute 207 in memory; the file on disk is never edited.

The PI e-mail cells here are synthetic; production stores the real cell 1:1 and never
serves or exports it.

| slice row | source data row (0-based) | case |
|---|---|---|
| 1 | 0 | dated, located, PN value with QF TPN, PI e-mail present |
| 2 | 1 | same estuary, other position |
| 3, 4 | 142, 143 | one position, two depths (1.0 m, 4.0 m) — two samples |
| 5 | 5693 | comment cell wrapped in double quotes |
| 6 | 7792 | QF DOC = 6, empty Sample ID |
| 7 | 21379 | QF DOC = 1 with no DOC value |
| 8 | 23336 | location with a trailing NBSP |
| 9 | 34730 | dated, latitude but no longitude → unmappable |
| 10 | 36612 | location-only line: no date, no coordinates → unmappable |
| 11 | 36613 | the line that continues row 10's location ("Bight") |
| 12 | 63030 | numeric-looking PN method ("5.4") with an empty PN value |
