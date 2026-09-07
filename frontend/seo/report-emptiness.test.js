import { describe, expect, it } from "vitest";
import { reportHasStatistics } from "./report-shape.js";

// Payload shapes copied from production 2026-08-23, not invented.
const EMPTY = {                       // /report/chess:Snake Pit
  platform_id: "chess:Snake Pit",
  risk_rating: "Low",
  narrative: "",
  key_stats: {},
  finding_count: 0,
  claim_count: 16,                    // ← nonzero, and renders nothing
};
const POPULATED = {                   // /report/3902749
  platform_id: "3902749",
  risk_rating: "Critical",
  narrative: "Argo float 3902749 drifted 310.3 km over the period ...",
  key_stats: { profile_count: 5, alarm_count: 0, total_distance_km: 310.3 },
  finding_count: 5,
  claim_count: 1,
};

describe("reportHasStatistics", () => {
  it("rejects the empty report that Search Console flagged as a soft 404", () => {
    expect(reportHasStatistics(EMPTY)).toBe(false);
  });

  it("accepts a populated report", () => {
    expect(reportHasStatistics(POPULATED)).toBe(true);
  });

  // The trap: claim_count is 16 on a page that renders nothing but em dashes.
  // A predicate built on the record's counters keeps exactly the URLs the fix
  // exists to drop.
  it("is not fooled by a nonzero claim_count on an empty report", () => {
    expect(EMPTY.claim_count).toBeGreaterThan(0);
    expect(reportHasStatistics(EMPTY)).toBe(false);
  });

  // The brief asked what happens to PARTIAL data, so it is answered here rather
  // than left to fall back into the 200-with-dashes shape by accident.
  it("keeps a report with one key_stat and no narrative", () => {
    expect(reportHasStatistics({ ...EMPTY, key_stats: { profile_count: 2 } })).toBe(true);
  });

  it("keeps a report with a narrative and no key_stats", () => {
    expect(reportHasStatistics({ ...EMPTY, narrative: "Float drifted 12 km." })).toBe(true);
  });

  it("treats a whitespace-only narrative as no narrative", () => {
    expect(reportHasStatistics({ ...EMPTY, narrative: "   \n" })).toBe(false);
  });

  it("does not throw on a missing or malformed payload", () => {
    expect(reportHasStatistics(null)).toBe(false);
    expect(reportHasStatistics({})).toBe(false);
    expect(reportHasStatistics({ narrative: null, key_stats: null })).toBe(false);
  });
});
