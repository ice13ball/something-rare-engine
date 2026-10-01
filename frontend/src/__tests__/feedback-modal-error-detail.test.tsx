// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// 2026-09-29: FeedbackModal showed the same generic "Something went wrong"
// text for every non-OK response, hiding the server's actual reason (e.g.
// "Too many links"), and gave the user no clue what to fix. Fixed to surface
// `detail` from the JSON body when present, and to keep the typed message in
// the textarea after an error so nothing is lost.
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, cleanup, screen, fireEvent, waitFor } from "@testing-library/react";
import { FeedbackModal } from "../components/FeedbackModal";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

async function typeAndSend(message: string) {
  render(<FeedbackModal onClose={() => {}} />);
  const box = document.querySelector("textarea") as HTMLTextAreaElement;
  fireEvent.change(box, { target: { value: message } });
  const sendButton = screen.getByRole("button", { name: /send/i });
  fireEvent.click(sendButton);
  return box;
}

describe("FeedbackModal — surfacing server error detail", () => {
  it("shows the server's detail on a 400 and keeps the typed message", async () => {
    vi.stubGlobal("fetch", vi.fn(() =>
      Promise.resolve({
        ok: false,
        status: 400,
        json: () => Promise.resolve({ detail: "Too many links" }),
      } as Response)));

    const box = await typeAndSend("check out https://a.cz https://b.cz https://c.cz https://d.cz");

    await waitFor(() => {
      expect(screen.getByText(/Too many links/)).toBeInTheDocument();
    });
    expect(box.value).toContain("https://a.cz");
  });

  it("shows the generic error text on a network failure", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new Error("network down"))));

    const box = await typeAndSend("hello there");

    await waitFor(() => {
      expect(screen.getByText(/Something went wrong/)).toBeInTheDocument();
    });
    expect(box.value).toBe("hello there");
  });
});
