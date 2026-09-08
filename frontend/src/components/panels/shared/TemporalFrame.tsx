// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

/**
 * WHEN a layer's data is from — shown on the layer itself, not buried in a tab.
 *
 * ⛔ This is not the sync date. "Dates & Freshness" reports when WE last refreshed
 * our copy; this reports the period the DATA covers. A layer synced this morning
 * can be a 1955–2017 climatology, and a layer we last pulled a year ago can hold
 * measurements taken last week. Conflating them is the whole reason this exists.
 *
 * `kind` carries more weight than the span. Two layers can both say "1955–2017"
 * and mean incompatible things — dated observations a model may filter by period,
 * versus one averaged value per cell that cannot be filtered at all. The one-line
 * meaning is rendered INLINE rather than hidden behind a hover, because a reader
 * deciding whether to trust a value is exactly the reader who will not hover.
 */

// ⛔ Must stay identical to KINDS in backend/layer_temporal_coverage.py, which is
// also the database CHECK constraint. test_the_two_kind_vocabularies_agree fails if
// they drift. ("live", for rolling feeds, belongs here the day a live layer is
// anchored — adding it to one side only would be rejected by the constraint.)
export type CoverageKind =
  | "observations" | "climatology" | "modelled"
  | "compilation" | "publication";

export interface Coverage {
  start_year: number | null;
  end_year: number | null;
  kind: CoverageKind;
  wording: string;
  source_url: string | null;
  verified_on: string;
}

/** What each kind means for someone deciding whether to reuse the numbers. */
const KIND_MEANING: Record<CoverageKind, string> = {
  observations: "dated measurements — can be filtered by period",
  climatology:  "one averaged value per cell — cannot be filtered by period",
  modelled:     "derived product — this is the span of its inputs",
  compilation:  "assembled from many studies — record dating is partial",
  publication:  "release year only — the source never stated when the data was collected",
};

/**
 * The span, rendered at the precision we actually have.
 *
 * ⛔ An open end is written "ongoing", never stamped with the current year: an
 * ongoing programme labelled "2003–2026" ages into a lie the moment nobody
 * updates it, and the lie is invisible.
 */
function spanText(c: Coverage): string {
  const { start_year: a, end_year: b } = c;
  if (a == null && b == null) return "period not established";
  if (a != null && b == null) return `${a}–ongoing`;
  if (a == null && b != null) return `until ${b}`;
  if (a === b) return String(a);
  return `${a}–${b}`;
}

export function TemporalFrame({ coverage }: { coverage?: Coverage | null }) {
  if (!coverage) return null;
  return (
    <p className="text-white/80 text-[15px] leading-[1.6] mb-2">
      <span className="text-white/75 font-mono text-[13px] uppercase tracking-wider">
        Data from →{" "}
      </span>
      <span className="font-mono text-white/95">{spanText(coverage)}</span>
      <span className="text-white/60"> · {KIND_MEANING[coverage.kind]}</span>
      {/* The publisher's own words, so the claim above is checkable rather than
          taken on trust. Small, but present — not a hover. */}
      <span className="block text-white/50 text-[12px] leading-snug mt-0.5">
        {coverage.wording}
        {coverage.source_url ? (
          <>
            {" "}
            <a
              href={coverage.source_url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-orange-300/70 hover:text-orange-200 underline underline-offset-2 decoration-orange-400/30"
            >
              source
            </a>
          </>
        ) : null}
      </span>
    </p>
  );
}
