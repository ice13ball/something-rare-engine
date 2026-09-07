// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// Proves the component-test harness end to end — jsdom, RTL, and the vitest config
// wiring all actually work together, not just that vitest itself runs.
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

function Hello({ name }: { name: string }) {
  return <p>Hello, {name}!</p>;
}

describe("component test harness", () => {
  it("renders and queries a component", () => {
    render(<Hello name="world" />);
    expect(screen.getByText("Hello, world!")).toBeInTheDocument();
  });
});
