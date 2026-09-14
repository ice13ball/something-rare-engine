// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// The notice exists because the alternative was silence: `?focus=` read
// `if (found) { open it }` and cleared the param either way, so a link to a
// vanished object opened nothing and said nothing — and the reader concluded
// that was the sender's point.
//
// ⛔ A test that only checks "no panel opened" cannot tell a silent miss from a
// noisy one, which is the whole bug. These assert the reader is TOLD.
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, cleanup, screen } from "@testing-library/react";

import { FocusUnavailableNotice } from "../components/FocusUnavailableNotice";

beforeEach(() => { vi.restoreAllMocks(); });
afterEach(() => { cleanup(); });

describe("FocusUnavailableNotice", () => {
  it("says nothing when nothing failed", () => {
    const { container } = render(<FocusUnavailableNotice failures={[]} onDismiss={() => {}} />);
    expect(container.firstChild).toBeNull();
  });

  it("names what could not be opened, and announces it", () => {
    render(
      <FocusUnavailableNotice
        failures={[{ layerId: "hydrothermal-vents", featureId: "Lucky Strike" }]}
        onDismiss={() => {}}
      />,
    );
    // Announced, not merely drawn — this arrives on page load.
    expect(screen.getByRole("status")).toBeTruthy();
    expect(screen.getByText("Lucky Strike")).toBeTruthy();
    // ⛔ Positive control: the panel really rendered its own copy, so the
    // assertions above are about content and not about an empty container.
    expect(document.body.textContent!.length).toBeGreaterThan(40);
  });

  it("adds the ageing-identifier line only for sources that regenerate ids", () => {
    const { unmount } = render(
      <FocusUnavailableNotice
        failures={[{ layerId: "contracts", featureId: "ISA-1" }]}
        onDismiss={() => {}}
      />,
    );
    const withoutNote = document.body.textContent!;
    unmount();

    render(
      <FocusUnavailableNotice
        failures={[{ layerId: "biodiversity-hotspots", featureId: "abc", idRegenerates: true }]}
        onDismiss={() => {}}
      />,
    );
    const withNote = document.body.textContent!;
    // Both sides non-empty before comparing — otherwise "longer" proves nothing.
    expect(withoutNote.length).toBeGreaterThan(40);
    expect(withNote.length).toBeGreaterThan(withoutNote.length);
  });

  it("shows the identifier alone when the layer is unknown", () => {
    // An untyped `?focus=<value>` is searched across several layers, so there
    // is no layer to name. A dangling separator would imply one.
    render(
      <FocusUnavailableNotice failures={[{ layerId: "", featureId: "WMO-6903" }]} onDismiss={() => {}} />,
    );
    expect(screen.getByText("WMO-6903")).toBeTruthy();
    expect(document.body.textContent).not.toMatch(/·\s*WMO-6903/);
  });
});
