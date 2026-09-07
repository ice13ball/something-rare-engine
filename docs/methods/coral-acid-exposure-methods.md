# Coral Acidification Exposure — Methods Note

**Status: DRAFT.** This note is committed to the repository as a citable methods
record. It has **not** been published to Zenodo and no DOI has been minted for it.
Publishing a version record is a separate, explicit, per-publish decision (a DOI is
irreversible) — see "Publication status" at the end of this note.

## What this is, and what it is not

This note documents two related additions to Abyssal Claims:

1. **Aragonite Horizon Shift** — a new `horizon-shift` variable inside the existing
   `ocean-acidification` field layer, showing how the aragonite saturation-horizon
   depth has moved between the preindustrial ocean and the present-day GLODAP
   climatology.
2. **Coral Acidification Exposure (`coral-acid-exposure`)** — an analysis layer that
   co-locates our own modeled deep-sea coral (VME) habitat suitability with that
   horizon shift, and reports what fraction of modeled coral habitat now sits below
   a horizon it was historically above.

**This is a secondary analysis of well-characterised public data, performed with an
established method.** Reconstructing a preindustrial aragonite saturation state from
GLODAP dissolved inorganic carbon (DIC) fields via anthropogenic-carbon (Cant)
back-correction is not a new technique — it is the same approach used by Feely et al.
(2004, 2009) and Jiang et al. (2015) to describe the shoaling of the aragonite
saturation horizon. **The contribution here is not a new scientific finding.** It is
the co-location of that established reconstruction with our own MaxEnt VME
suitability model, and the derived suitability-weighted exposure statistic that
falls out of combining the two. Both inputs are themselves modeled products with
real, disclosed uncertainty (see "Uncertainty" below). Nothing in this layer should
be read as a discovery about coral decline, a rate, or a prediction.

**Exposure is not loss.** Aragonite undersaturation (Ω_A < 1) means the water is
thermodynamically corrosive to aragonite — it does **not** mean coral present in
that cell is dead, dying, or doomed. Live scleractinian and other cold-water corals
are documented growing below the local saturation horizon, at an elevated metabolic
cost of biomineralisation. This layer reports a **chemical exposure state**, not a
biological outcome. The panel, legend, and this note deliberately avoid words like
"at-risk", "threatened", "loss", or "impact" for exactly this reason.

**This is a snapshot comparison, not a trend.** The "present" state is the GLODAP
v2.2016b mapped climatology, whose synthesis reference year is approximately 2002
(pre-industrial DIC is corrected back to a nominal 1850 reference using GLODAP's own
Cant estimate). There are exactly two epochs. No per-year rate, no extrapolation to
today or to any future date, is computed or implied anywhere in this layer.

## Reconstruction method

### Inputs

All inputs are read from the same GLODAPv2.2016b Mapped Climatology NetCDF product
already used by the `ocean-carbon` (`glodap_carbon.py`) and `ocean-acidification`
(`acidification.py`) layers — there is no separate download for this feature.

| Quantity | GLODAP variable | Role |
|---|---|---|
| Present-day DIC | `TCO2` | present-epoch carbon input |
| Preindustrial DIC | `PI_TCO2` | preindustrial-epoch carbon input (GLODAP's own Cant-corrected field) |
| Total alkalinity | `TAlk` | **held constant across both epochs** (see Assumptions) |
| Phosphate | `PO4` | nutrient input to the carbonate system |
| Silicate | `silicate` | nutrient input to the carbonate system |
| Temperature | in-situ temperature | required for equilibrium constants |
| Salinity | practical salinity | required for equilibrium constants |

### PyCO2SYS configuration

Aragonite saturation state (Ω_A) is reconstructed for **both** epochs with
[PyCO2SYS](https://pyco2sys.readthedocs.io/), using DIC + TAlk + nutrients +
temperature + salinity as the carbonate-system inputs. Both epochs run through
**one identical CO2SYS configuration** — same code path, same options, same
constants — differing only in which DIC field (`TCO2` vs `PI_TCO2`) is supplied.

The single carbonic-acid dissociation-constant option that matters for
reproducibility is set explicitly:

```
opt_k_carbonic = 10   # Lueker et al. (2000)
```

This is the constant set GLODAP itself documents using for its own `OmegaA`/`OmegaC`
products, chosen so the reconstruction is directly comparable to GLODAP's published
values (see QC below). It is set explicitly in code rather than left at a PyCO2SYS
default, so a future PyCO2SYS version bump cannot silently change which constants
this layer uses.

Running both epochs through the identical configuration is the single most
important method decision in this feature: because both epochs share every
constant, every nutrient field, and every code path, any systematic bias in the
reconstruction (choice of dissociation constants, small nutrient-field errors,
resolution artefacts) affects both epochs equally and **cancels to first order in
the difference**. See "Why the difference-of-reconstructions design" below.

### Saturation-horizon depth

Given a reconstructed Ω_A profile at a grid cell (one value per GLODAP depth
level), `acidification.saturation_horizon(omega_col, depths)` derives the depth (in
metres) at which Ω_A crosses below 1.0:

- Walks the depth column top-down.
- If the shallowest level is already below 1.0, returns that shallowest depth.
- Otherwise linearly interpolates the crossing depth between the last
  supersaturated level and the first sub-1.0 level.
- If the column never crosses below 1.0 anywhere in the water column, the
  function returns `math.inf` — the horizon does not exist in this column; it is
  supersaturated at every measured depth ("always safe" in the depth-only sense).
- If there is no valid data at all for the column (every level NaN), it returns
  `None`.

NaN levels within an otherwise valid column are skipped rather than breaking the
top-down walk across the gap — the same "skip, don't zip-truncate" discipline used
elsewhere in this codebase for ragged/gappy source arrays (see the WOD oxygen
ragged-array fix).

This same function, unchanged, computes **both**:
- `horizon` — the shift variable's present-day horizon, from **GLODAP's own
  published `OmegaA`** field (no PyCO2SYS involved).
- `horizon_today_recon` / `horizon_preindustrial_recon` — the reconstructed pair,
  from PyCO2SYS Ω_A on `TCO2` and `PI_TCO2` respectively.

## Why the difference-of-reconstructions design

There is no published preindustrial `OmegaA` in GLODAP — GLODAP only publishes
present-day `OmegaA`/`OmegaC`. So a preindustrial horizon can only ever come from
our own PyCO2SYS reconstruction. The design decision this note records is:

> **Both the horizon shift AND the exposure classification use the reconstructed
> horizon pair for both epochs (`horizon_today_recon` vs
> `horizon_preindustrial_recon`) — never GLODAP's published `horizon` for "today"
> differenced against our own reconstruction for "preindustrial".**

Mixing a published quantity and a reconstructed quantity in a single difference
would confound two independent things: the real historical shoaling of the horizon,
and any systematic bias between GLODAP's own carbonate-system solver and PyCO2SYS's
(different constant defaults, different code, potentially different rounding of
intermediate quantities). By reconstructing *both* epochs through the identical
PyCO2SYS configuration, that solver-choice bias is present in both terms of the
difference and cancels out — what remains is (to first order) the true change
between the two DIC fields.

The shipped `aragonite`/`calcite` field views in `ocean-acidification` are
unaffected by any of this — they continue to read GLODAP's own `OmegaA`/`OmegaC`
directly, as the ocean-acidification layer documents. PyCO2SYS is
used **only** for the two DIC-based reconstructions described here, and for the QC
step below. It is never substituted for the GLODAP-published values on the map.

## QC validation

Because the whole feature rests on trusting a PyCO2SYS reconstruction that has no
preindustrial counterpart to check against, the present-day half of the
reconstruction is validated against something that *does* have a published
counterpart: GLODAP's own present-day `OmegaA`.

`qc_omega_vs_published()` draws **3,000 random valid grid cells** (present-day,
non-NaN in both the reconstructed and published fields) and computes, per cell:

```
difference = Ω_A(reconstructed, TCO2)  −  Ω_A(published, OmegaA)
```

**Result: median difference +0.00167, IQR [−0.0087, +0.0088].**

That is, across 3,000 independently sampled cells, the reconstruction and GLODAP's
own published value agree to within about ±0.01 Ω units at the median, with the
central 50% of differences spanning less than 0.02 Ω units — small relative to the
±1.0 unit that separates supersaturated from corrosive water. This is the number
that licenses trusting the preindustrial reconstruction, which has no independent
check available: if the identical method reproduces GLODAP's own published present-
day field this closely, the same method applied to `PI_TCO2` is credible for the
epoch that cannot otherwise be verified.

This QC step is computed live (not a one-off notebook calculation) so it can be
re-run against any future GLODAP or PyCO2SYS revision to confirm the agreement
still holds.

## Exposure classification

For each modeled VME coral cell (see "VME provenance" below), seafloor depth is
looked up from **GEBCO 2024** bathymetry (the same grid used elsewhere in this
codebase). GEBCO stores elevation, not
depth: negative values are below sea level. Seafloor depth is therefore
`depth_m = -elevation_m` for elevation < 0; cells with elevation ≥ 0 (land) are
excluded.

That seafloor depth is compared against the two reconstructed horizon depths
(`horizon_today_recon`, `horizon_preindustrial_recon`) to assign one of four
mutually exclusive states:

| State | Condition | Reading |
|---|---|---|
| `newly_corrosive` | seafloor below today's horizon, **above** the preindustrial horizon | the headline state: this cell used to sit in supersaturated water and now sits below the horizon |
| `corrosive_preindustrial` | seafloor below **both** horizons | already below the horizon before industrial-era change; not newly exposed |
| `supersaturated` | seafloor above today's horizon | above the horizon in both epochs |
| `no_data` | seafloor depth, either horizon, or the VME suitability value is missing | cannot be classified — excluded from all downstream statistics |

`math.inf` for a horizon (column never crosses Ω=1 — always supersaturated at every
depth) is treated as: seafloor is always above it, so the cell reads
`supersaturated` for that epoch's contribution to the comparison, never
`no_data` on that account alone.

## Suitability-weighted exposure statistic

A cell being classified `newly_corrosive` says nothing about how good that cell is
as coral habitat — a marginal-suitability cell counted the same as a peak-suitability
cell would overweight areas the VME model considers poor habitat in the first
place. Rather than pick an arbitrary suitability cutoff ("habitat" vs "not
habitat") and count cells above it, the headline statistic weights every cell by
its own modeled suitability:

```
weighted_exposure = Σ(suitability_i × is_exposed_i)  /  Σ(suitability_i)
```

summed over all cells with valid data (`no_data` cells excluded from **both** the
numerator and the denominator — they contribute nothing to either sum, rather than
being treated as zero-suitability or non-exposed). `is_exposed_i` is 1 for
`newly_corrosive` cells and 0 otherwise (`corrosive_preindustrial` and
`supersaturated` cells contribute their suitability to the denominator only).

This removes the need to justify any single "what counts as habitat" threshold.
Because that removal is itself a modeling choice with its own trade-offs, the
summary endpoint also reports a **threshold-sensitivity table** at three
conventional cutoffs (suitability ≥ 0.3, ≥ 0.5, ≥ 0.7): the plain fraction of cells
above each threshold that are `newly_corrosive`. Presenting the weighted statistic
alongside the threshold table lets a reader see how sensitive the headline number
is to the choice of threshold, rather than presenting a single number as if it were
threshold-free in some absolute sense.

## VME provenance and skill metrics

The habitat-suitability input is this platform's own MaxEnt species distribution
model (`vme_sdm.py`, shipped 2026-07-16). Relevant figures, carried over unchanged into
this analysis:

- Trained on NOAA DSCRTP presence records for the `reef_scleractinia_v1` taxon set
  (n = 167 occurrences).
- Predictors: GEBCO 2024 bathymetry/slope; **Dutkiewicz et al. 2015** seabed
  substrate (see "CC-BY-NC lineage" below); WOA23 temperature/salinity/nutrients;
  ISAS20 oxygen; GLODAPv2.2016b carbonate chemistry (via PyCO2SYS, as a *predictor*
  input to the SDM — a different use of PyCO2SYS from the epoch reconstruction
  described in this note).
- Skill: **AUC 0.875**, Boyce index 0.518.
- 3,837 hex cells at first bake (predictor-limited coverage, not a full-ocean
  grid).

The VME model's own uncertainty (a moderate-to-good but not excellent AUC, a
Boyce index indicating imperfect calibration to the true presence distribution)
propagates directly into the exposure statistic: a suitability value the model
gets wrong will move that cell's contribution to the weighted exposure in a
direction the model itself cannot flag.

## Assumptions and disclosed limitations

- **Total alkalinity (TAlk) is held constant between the preindustrial and
  present epochs.** GLODAP does not publish a preindustrial TAlk field distinct
  from present-day TAlk (alkalinity is not significantly altered by anthropogenic
  CO₂ uptake at the timescale and precision relevant here, unlike DIC). This is a
  standard simplifying assumption in the Feely/Jiang-style literature this method
  follows, not something this platform introduces — but it is still an assumption,
  and it means any real historical change in alkalinity (from, e.g., large-scale
  calcification or weathering shifts) is not captured.
- **The "present" epoch is GLODAPv2.2016b's own synthesis reference, approximately
  2002**, not 2026. Nothing is extrapolated to the current year.
- **1°×1° horizontal resolution, 33 discrete depth levels** — the native GLODAP
  mapped-climatology grid. Sub-grid-scale seafloor features (seamounts, canyon
  walls) that fall within a single 1° cell are not resolved; a cell's classification
  reflects the grid-cell-average water column, not necessarily the exact
  micro-habitat a coral colony occupies.
- **Seafloor depth comes from GEBCO 2024**, itself a blend of measured
  (multibeam-surveyed) and modelled/satellite-derived bathymetry in different
  regions — see the bathymetry-confidence enrichment for the
  measured/indirect/unknown split. This exposure layer does not itself carry a
  per-cell bathymetric confidence flag; that enrichment exists independently and
  is not currently joined into this analysis.
- **`no_data` fraction** — cells are excluded when seafloor depth, either
  horizon, or VME suitability is missing (e.g. VME predictor coverage gaps,
  GEBCO land cells inside a nominally oceanic hex, GLODAP grid cells with no valid
  carbonate-chemistry data at any depth). The `no_data` count is reported
  alongside the summary statistic specifically so a reader can judge how much of
  the modeled habitat the headline number is actually describing, rather than
  treating an unqualified percentage as covering "all coral habitat".

## Uncertainty — this is a double-modeled quantity

Every exposure statistic in this layer combines two independently modeled
products, each with its own disclosed uncertainty, and the analysis does not
attempt to propagate the two into a single combined confidence interval:

1. **VME suitability** — MaxEnt output, AUC 0.875 / Boyce 0.518 (moderate-to-good
   discrimination, imperfect calibration), trained on a modest presence-only
   sample (n = 167).
2. **Ω_A climatology** — a 1°×1° reconstruction from a mapped DIC/TAlk/nutrient
   climatology, itself an interpolation of sparse real cruise/mooring
   measurements, plus the reconstruction-specific sources of error: TAlk held
   constant across epochs, whatever error is present in GLODAP's own Cant
   (anthropogenic carbon) estimate that produces `PI_TCO2`, and the DIC
   measurement/mapping error inherited from the underlying GLODAP synthesis.

A reader should treat every number in this layer — the per-cell state, the
weighted fraction, the threshold table — as carrying meaningful uncertainty from
both sources, not as a precise measurement.

## Implementation summary (for engineering reference)

- **Table:** `vme_exposure_cells` — one row per VME hex cell (`vme_cells` joined
  to `density_hex_cells` for cell geometry, filtered to
  `taxon_set = reef_scleractinia_v1`).
- **Bake:** in-process, startup delay `_BAKE_STARTUP_DELAY = 2460 s`, scheduled
  after both the `ocean-acidification` bake and the GEBCO-derived bathymetry grid
  it depends on; the bake order for this layer is load-bearing.
- **`math.inf` horizons are stored as SQL `NULL`** in `vme_exposure_cells` — the
  `state` column already encodes the "never crosses Ω=1" case
  (`supersaturated`), so there is no information loss in not storing an infinite
  float; storing `NULL` also avoids the same non-finite-JSON problem documented
  for the `ocean-acidification` `horizon.png`/export path (`Infinity` is not valid
  JSON per RFC 8259).
- **Endpoints:** `/v1/coral-exposure/meta`, `/v1/coral-exposure/hexes`,
  `/v1/coral-exposure/point`, `/v1/coral-exposure/summary`.
- **Sync source key:** `coral-acid-exposure`.

## CC-BY-NC lineage and the monetisation coupling

The VME suitability model — one of the two inputs to this analysis — includes
**Dutkiewicz et al. 2015** seabed substrate as one of several predictors (alongside
GEBCO, WOA23, ISAS, and GLODAP). Dutkiewicz et al. 2015 is licensed **CC-BY-NC**
(non-commercial). This layer is publishable as part of Abyssal Claims specifically
**because the platform itself is non-monetised** — it is a portfolio and showcase
project, not a business, and the paid API-key
management subsystem, which currently issues no paid tier.

This is a **documented constraint, not a present blocker**: if this platform, or
this specific layer, were ever put behind a paid tier of the API-key subsystem, the
CC-BY-NC lineage running through the VME predictor stack (and therefore into this
exposure layer, which consumes VME suitability) would need to be re-assessed before
that change ships. This note exists in part so that re-assessment has a clear paper
trail to start from, rather than requiring someone to re-derive the predictor
lineage from code.

## Publication status

This methods note is committed to the repository (`docs/methods/`) as the citable
record for this feature, ahead of any Zenodo action. **It has not been published to
Zenodo, and no DOI (concept or version) has been minted for it.** Publishing a new
version record against the existing concept DOI is a distinct, explicit,
per-publish decision — a DOI is irreversible once minted — and is out of scope for
this note.

## References

- Feely, R.A., et al. (2004). Impact of Anthropogenic CO2 on the CaCO3 System in
  the Oceans. *Science* 305, 362–366.
- Feely, R.A., et al. (2009). Ocean acidification: Present conditions and future
  changes in a high-CO2 world. *Oceanography* 22(4), 36–47.
- Jiang, L.-Q., Feely, R.A., Carter, B.R., et al. (2015). Climatological
  distribution of aragonite saturation state in the global oceans. *Global
  Biogeochemical Cycles* 29, 1656–1673.
- Lauvset, S.K., et al. (2016). A new global interior ocean mapped climatology:
  the 1°×1° GLODAP version 2. *Earth System Science Data* 8, 325–340.
- Key, R.M., et al. (2015). Global Ocean Data Analysis Project, Version 2
  (GLODAPv2), ORNL/CDIAC-162, NDP-093.
- Lueker, T.J., Dickson, A.G., Keeling, C.D. (2000). Ocean pCO2 calculated from
  dissolved inorganic carbon, alkalinity, and equations for K1 and K2: validation
  based on laboratory measurements of CO2 in gas and seawater at equilibrium.
  *Marine Chemistry* 70, 105–119.
- Dutkiewicz, A., Müller, R.D., O'Callaghan, S., Jónasson, H. (2015). Census of
  seafloor sediments in the world's ocean. *Geology* 43(9), 795–798. (CC-BY-NC)
- Humphreys, M.P., et al. — PyCO2SYS: marine carbonate system calculations in
  Python.
