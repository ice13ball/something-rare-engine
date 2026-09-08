import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, waitFor } from "@testing-library/react";

import { PermafrostThawPanel } from "../components/panels/arctic/PermafrostThawPanel";

/**
 * The bulk payload no longer carries imagery/authors/source_doi/data_source_type,
 * so the panel fetches them per feature. Two things about that fetch are load
 * bearing and neither is visible in a snapshot:
 *
 *  1. It must send `source`. The row's real key is (source, unique_id) — that is
 *     what the unique index is on. Dropping `source` would still pass every other
 *     test today, and would start returning another feature's provenance the day
 *     a second source ships a colliding id. No error would appear anywhere.
 *  2. A failed fetch must leave the panel rendering its bulk fields. The detail is
 *     an enrichment, not the content.
 */
const BULK = {
  unique_id: "TEST-UID-1",
  source: "alaska_webb",
  feature_name: "TEST Feature",
  feature_category: "thermokarst lake",
  feature_type: "lake",
  thaw_type: "non-abrupt",
  obs_start_year: 1985,
  obs_end_year: 2015,
  date_precision: "campaign",
};

describe("PermafrostThawPanel detail fetch", () => {
  beforeEach(() => vi.restoreAllMocks());
  afterEach(() => vi.restoreAllMocks());

  it("sends source alongside unique_id, because (source, unique_id) is the real key", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ imagery: null, authors: null, source_doi: null,
                           data_source_type: null, obs_start: null, obs_end: null }),
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<PermafrostThawPanel properties={BULK} />);

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const url = String(fetchMock.mock.calls[0][0]);
    expect(url).toContain("/by-id/TEST-UID-1");
    expect(url).toContain("source=alaska_webb");
  });

  it("still renders the bulk fields when the detail fetch fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network down")));

    const { findByText } = render(<PermafrostThawPanel properties={BULK} />);

    // The name comes from the bulk properties; a dead detail fetch must not
    // blank the panel or throw.
    expect(await findByText(/TEST Feature/)).toBeTruthy();
  });
});
