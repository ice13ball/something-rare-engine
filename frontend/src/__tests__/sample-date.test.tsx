// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { SampleDate } from "../components/panels/shared/SampleDate";

it("renders a day-precision date in full", () => {
  render(<SampleDate precision="day" year={2008} month={8} day={12} />);
  expect(screen.getByText("2008-08-12")).toBeInTheDocument();
});

it("never widens a year into a day", () => {
  render(<SampleDate precision="year" year={2008} />);
  expect(screen.getByText("2008")).toBeInTheDocument();
  expect(screen.queryByText(/2008-01-01/)).toBeNull();
  expect(screen.queryByText(/2008-01/)).toBeNull();
});

it("never narrows a day into a year", () => {
  render(<SampleDate precision="day" year={2008} month={8} day={12} />);
  expect(screen.queryByText(/^2008$/)).toBeNull();
});

it("renders a month without inventing a day", () => {
  render(<SampleDate precision="month" year={2008} month={8} />);
  expect(screen.getByText("2008-08")).toBeInTheDocument();
});

it("falls back to the campaign window when there is no sample date", () => {
  render(<SampleDate precision="campaign" campaignStart="2008-06-01" campaignEnd="2008-09-15" />);
  expect(screen.getByText(/2008-06-01 → 2008-09-15/)).toBeInTheDocument();
});

it("says so when the source gave no date, rather than rendering nothing", () => {
  const { container } = render(<SampleDate precision="none" />);
  expect(container.textContent?.trim()).not.toBe("");
});

it("shows the source comment beside the date", () => {
  render(<SampleDate precision="year" year={2001} comment="samples taken in 2003 and 2004" />);
  expect(screen.getByText(/samples taken in 2003 and 2004/)).toBeInTheDocument();
});

it("treats a null precision with a known year as year-precision, not no-date", () => {
  // date_precision is NULL on every row ingested before the column existed;
  // sampling_year is still real. Must not claim "no date at source".
  render(<SampleDate precision={null} year={2008} />);
  expect(screen.getByText("2008")).toBeInTheDocument();
  expect(screen.queryByText(/no date at source/i)).toBeNull();
});
