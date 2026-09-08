// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { TemporalFrame, type Coverage } from "../components/panels/shared/TemporalFrame";

const base: Coverage = {
  start_year: 1971, end_year: 2018, kind: "climatology",
  wording: "recent field: ISAS20 2014-2018 · baseline: WOA23N 1971-2000",
  source_url: "https://doi.org/10.17882/52367", verified_on: "2026-09-08",
};

it("shows the span", () => {
  render(<TemporalFrame coverage={base} />);
  expect(screen.getByText("1971–2018")).toBeInTheDocument();
});

it("never stamps an ongoing programme with a closing year", () => {
  // ⛔ The whole point. "2003–2026" on an ongoing series ages into a lie the
  // moment nobody updates it, and nothing on screen reveals that it has.
  render(<TemporalFrame coverage={{ ...base, start_year: 2003, end_year: null }} />);
  expect(screen.getByText("2003–ongoing")).toBeInTheDocument();
  expect(screen.queryByText(/2003–20\d\d/)).toBeNull();
});

it("collapses a single-year span instead of writing 2015–2015", () => {
  render(<TemporalFrame coverage={{ ...base, start_year: 2015, end_year: 2015 }} />);
  expect(screen.getByText("2015")).toBeInTheDocument();
});

it("states an unestablished period rather than rendering blank", () => {
  // A blank reads as "still loading", which is a different claim.
  render(<TemporalFrame coverage={{ ...base, start_year: null, end_year: null }} />);
  expect(screen.getByText("period not established")).toBeInTheDocument();
});

it("spells out that a climatology cannot be filtered by period", () => {
  // The span alone is not the answer to 'may I pool this with recent data'.
  render(<TemporalFrame coverage={base} />);
  expect(screen.getByText(/cannot be filtered by period/)).toBeInTheDocument();
});

it("distinguishes observations, which can be filtered", () => {
  render(<TemporalFrame coverage={{ ...base, kind: "observations" }} />);
  expect(screen.getByText(/can be filtered by period/)).toBeInTheDocument();
});

it("renders nothing at all when a layer has no anchor yet", () => {
  // Absent is honest; a guessed range would not be.
  const { container } = render(<TemporalFrame coverage={null} />);
  expect(container).toBeEmptyDOMElement();
});

it("carries the publisher's own wording so the claim is checkable", () => {
  render(<TemporalFrame coverage={base} />);
  expect(screen.getByText(/ISAS20 2014-2018/)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "source" })).toHaveAttribute(
    "href", "https://doi.org/10.17882/52367");
});
