// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// ⛔ "Missing" and "broken" must never share a code path. 400/404/410/422 mean
// the thing is not there -> 404. Anything else means we cannot tell -> 503 with
// Retry-After. A 200 carrying an empty shell during an outage is a de-indexing
// event across ~40 300 URLs, because Google cannot see an outage — only a page
// that renders nothing and answers 200.
//
// This file exists because the same classification lived in three places
// (fetchJsonOrThrow in render-page.js, fetchEntity in server.js, and the hub
// index loop), each carrying a comment warning that copies which disagree
// reintroduce the defect. Adding a retry to each would have made it three
// copies of two behaviours.

export class BackendUnavailable extends Error {}

const MISSING_STATUSES = new Set([400, 404, 410, 422]);

// Only 502 and 503. Both mean a proxy answered on the backend's behalf, which
// is the transient state a deploy creates. A refused connection or a timeout
// means nothing is listening: retrying it adds 1.5 s to every request during a
// real outage and delays the 503 that tells Google to come back later.
const RETRY_STATUSES = new Set([502, 503]);

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// The number of fetch attempts made before giving up. ONE named constant, used
// both as the loop bound and to decide whether there is another attempt left
// to sleep for — so a change to "how many times we try" cannot desync from
// "how many times we sleep between tries" the way two separate literals could.
const ATTEMPTS = 2;

export async function fetchUpstream(url, opts = {}) {
  const { timeoutMs = 5000, retryDelayMs = 1500, fetchImpl = fetch } = opts;
  let lastStatus;

  for (let attempt = 0; attempt < ATTEMPTS; attempt++) {
    let res;
    try {
      res = await fetchImpl(url, { signal: AbortSignal.timeout(timeoutMs) });
    } catch (err) {
      // Network error, DNS failure, or the AbortSignal timeout firing. Nothing
      // is listening — retrying would only delay the 503 by retryDelayMs.
      throw new BackendUnavailable(err?.message || String(err));
    }
    if (MISSING_STATUSES.has(res.status)) return null;
    if (res.ok) {
      try {
        return await res.json();
      } catch (err) {
        // A 200 whose body is not JSON is a broken backend, not a missing entity.
        throw new BackendUnavailable(`malformed JSON: ${err.message}`);
      }
    }
    if (!RETRY_STATUSES.has(res.status)) {
      throw new BackendUnavailable(`HTTP ${res.status}`);
    }
    lastStatus = res.status;
    if (attempt < ATTEMPTS - 1) await sleep(retryDelayMs);
  }
  throw new BackendUnavailable(`HTTP ${lastStatus}`);
}
