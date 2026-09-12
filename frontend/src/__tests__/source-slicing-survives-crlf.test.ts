// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// A test that measures the shape of source code must measure the same region on
// every checkout.
//
// `detail-panel-matrix.test.tsx` counts `layer === "..."` branches inside
// `PanelContent()` to prove the fixture list and the dispatch chain agree. It
// bounded that function with `src.indexOf("\n}\n")`. On a CRLF checkout that
// returns -1, and `slice(start, -1)` quietly widens the region to almost the
// whole file — the count then comes from the wrong text and the result is
// accidental, red or green.
//
// This file holds the slicing helper to the two properties that matter:
// it gives the SAME answer whatever the line endings are, and it THROWS rather
// than returning a wrong region when its anchors stop matching.
import { describe, it, expect } from "vitest";

import { sliceFunctionBody, toLf } from "./sliceSource";

// Deliberately built with explicit \n, then converted, so the two inputs differ
// only in line endings and nothing else.
const LF_SOURCE = [
  "const before = 'noise';",
  "function PanelContent() {",
  '  if (layer === "a") return 1;',
  '  if (layer === "b") return 2;',
  "}",
  "",
  "function After() {",
  '  if (layer === "c") return 3;',
  '  if (layer === "d") return 4;',
  "}",
  "",
].join("\n");

const CRLF_SOURCE = LF_SOURCE.replace(/\n/g, "\r\n");

const countBranches = (body: string) => (body.match(/layer === "[^"]*"/g) ?? []).length;

describe("sliceFunctionBody bounds the same region on any checkout", () => {
  it("finds exactly the target function's branches with LF endings", () => {
    const body = sliceFunctionBody(LF_SOURCE, "function PanelContent(");
    expect(countBranches(body)).toBe(2);
    expect(body).not.toContain("function After(");
  });

  it("finds exactly the same branches with CRLF endings", () => {
    // ⛔ This is the assertion the old `indexOf("\n}\n")` failed: it returned
    // -1, the slice ran to the end of the file, and the count became 4.
    const body = sliceFunctionBody(CRLF_SOURCE, "function PanelContent(");
    expect(countBranches(body)).toBe(2);
    expect(body).not.toContain("function After(");
  });

  it("gives byte-identical answers for the two line endings", () => {
    expect(sliceFunctionBody(CRLF_SOURCE, "function PanelContent(")).toBe(
      sliceFunctionBody(LF_SOURCE, "function PanelContent("),
    );
  });
});

describe("sliceFunctionBody refuses to guess", () => {
  it("throws when the signature is absent instead of slicing from 0", () => {
    expect(() => sliceFunctionBody(LF_SOURCE, "function Missing(")).toThrow(
      /signature not found/,
    );
  });

  it("throws when no closing brace follows instead of slicing to EOF", () => {
    const unterminated = "function PanelContent() {\n  if (layer === \"a\") return 1;\n";
    expect(() => sliceFunctionBody(unterminated, "function PanelContent(")).toThrow(
      /closing brace/,
    );
  });
});

describe("toLf", () => {
  it("normalises CRLF and a lone CR", () => {
    expect(toLf("a\r\nb\rc\nd")).toBe("a\nb\nc\nd");
  });
});
