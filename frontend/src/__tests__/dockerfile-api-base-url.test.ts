// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// Companion to seo-page-no-doubled-api-prefix.test.tsx. That test proves the
// rendered pages behave correctly when VITE_API_BASE_URL is unset — but it
// cannot see a regression in the Docker build itself, because Vitest never
// evaluates the Dockerfile. This test reads frontend/Dockerfile directly and
// fails if VITE_API_BASE_URL is ever set to a non-empty value again: every
// call site in src/ already hardcodes a literal "/api" prefix
// (`${API}/api/v1/...`), so baking another "/api" into the build env produces
// /api/api/v1/... in production only — the 2026-09-18 incident.
import { describe, it, expect } from "vitest";
import { readFileSync } from "fs";
import { join, dirname } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const dockerfilePath = join(__dirname, "..", "..", "Dockerfile");

describe("frontend/Dockerfile — VITE_API_BASE_URL must stay unset", () => {
  it("never sets VITE_API_BASE_URL to a non-empty value", () => {
    const contents = readFileSync(dockerfilePath, "utf8");
    const setLine = contents
      .split("\n")
      .find(line => /^\s*ENV\s+VITE_API_BASE_URL=/.test(line));

    if (!setLine) return; // not set at all — the correct, current state

    const value = setLine.split("=")[1]?.trim();
    expect(value, `Dockerfile sets VITE_API_BASE_URL=${value}, which doubles the ` +
      `hardcoded "/api" literal at every call site in src/ — see ` +
      `seo-page-no-doubled-api-prefix.test.tsx for what that breaks.`).toBeFalsy();
  });
});
