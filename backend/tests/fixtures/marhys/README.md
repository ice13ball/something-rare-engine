# MARHYS fixture — attribution

`marhys_slice.xlsx` is **24 rows copied verbatim** out of the published MARHYS
Database 4.0 workbook, kept here so the parser is tested against real source
bytes rather than an invented file.

**Source**

> Diehl, Alexander; Bach, Wolfgang (2024): *MARHYS Database 4.0* [dataset].
> PANGAEA, <https://doi.org/10.1594/PANGAEA.972999>

**Licence:** Creative Commons Attribution 4.0 International (CC-BY-4.0) —
<https://creativecommons.org/licenses/by/4.0/>. Redistribution is permitted with
attribution, which is why this excerpt may live in a public repository.

⭐ **The dataset's own terms require the base publication to be cited alongside
it.** From the PANGAEA record's header, verbatim: *"Please always cite the base
publication (Diehl & Bach, 2020; doi:10.1029/2020GC009385) along with this
dataset."* Citing only the PANGAEA DOI does not satisfy the terms.

> Diehl, A. & Bach, W. (2020): MARHYS (MARine HYdrothermal Solutions) Database:
> A Global Compilation of Marine Hydrothermal Vent Fluid, End-Member, and
> Seawater Compositions. *Geochemistry, Geophysics, Geosystems*,
> <https://doi.org/10.1029/2020GC009385>

Compiled at MARUM, University of Bremen; funded by DFG EXC 2077.

**What the 24 rows were chosen to cover** — every awkward case in the full file,
so the tests exercise reality rather than the happy path:

| case | rows |
|---|---|
| all four sample types (HF / EM / SW / STD) | 9 / 11 / 2 / 2 |
| latitude outside ±90° (Guaymas Basin, axes transposed in the source) | 3 |
| longitude sign-flipped (Saldanha, lands in Turkey) | 2 |
| no coordinates at all | 6 |
| latitude present, longitude absent | 2 |
| `Mg = 0` — a real end-member value, not a gap | 8 |
| samples the source never named (`Sample-ID` = "not given") | 3 |
| collection dates in several of the source's eight text formats | — |
