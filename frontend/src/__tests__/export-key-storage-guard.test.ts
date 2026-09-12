// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// Reading a preference must never be able to kill the panel that reads it.
//
// `getStoredKey()` is called as a LAZY useState INITIALISER
// (`ExportPanel.tsx`, `useState<string>(() => getStoredKey())`), so it runs
// during render. A `localStorage` getter that throws therefore throws inside
// React's render phase and takes the whole Export panel subtree down — not a
// degraded panel, an absent one.
//
// This is not hypothetical: in Safari's private mode (and with storage blocked
// by a policy or an extension) `localStorage` access throws a SecurityError
// rather than returning null. Every other storage reader in this codebase
// already wraps its access — `utils/mapState.ts`, `utils/depthCache.ts`,
// `utils/analytics.ts`, `utils/startupProfiles.ts`, `WelcomeOverlay.tsx`.
// `ExportKeyModal.tsx` was the single unguarded one.
//
// ⛔ The assertions below must FAIL if the try/catch is removed. That is the
// whole point: a guard that cannot go red is not a guard.
import { describe, it, expect, beforeEach, afterEach } from "vitest";

import { getStoredKey, setStoredKey, forgetKey } from "../components/ExportKeyModal";

const real = globalThis.localStorage;

/** Storage that throws on every operation, the way a blocked origin behaves. */
function installThrowingStorage() {
  const boom = () => {
    throw new DOMException("The operation is insecure.", "SecurityError");
  };
  Object.defineProperty(globalThis, "localStorage", {
    configurable: true,
    get() {
      return { getItem: boom, setItem: boom, removeItem: boom } as unknown as Storage;
    },
  });
}

/** Storage whose *property access itself* throws — Safari private mode's shape. */
function installThrowingAccessor() {
  Object.defineProperty(globalThis, "localStorage", {
    configurable: true,
    get() {
      throw new DOMException("The operation is insecure.", "SecurityError");
    },
  });
}

afterEach(() => {
  Object.defineProperty(globalThis, "localStorage", {
    configurable: true,
    writable: true,
    value: real,
  });
});

describe("export key storage survives a hostile localStorage", () => {
  it("getStoredKey returns an empty string instead of throwing", () => {
    installThrowingStorage();
    expect(() => getStoredKey()).not.toThrow();
    expect(getStoredKey()).toBe("");
  });

  it("getStoredKey survives storage whose property access throws", () => {
    // The harsher shape: the exception fires before any method is reached, so a
    // try/catch placed only around `.getItem(...)` is not enough — the whole
    // expression has to be inside it.
    installThrowingAccessor();
    expect(() => getStoredKey()).not.toThrow();
    expect(getStoredKey()).toBe("");
  });

  it("setStoredKey and forgetKey do not throw when the write is refused", () => {
    installThrowingStorage();
    expect(() => setStoredKey("abc")).not.toThrow();
    expect(() => forgetKey()).not.toThrow();
  });
});

describe("export key storage still works when storage is healthy", () => {
  // ⛔ Without this the fix could be "swallow everything and always return
  // empty", which passes every test above while quietly forgetting the user's
  // key on every render.
  beforeEach(() => {
    real.clear();
  });

  it("round-trips a key and forgets it on request", () => {
    expect(getStoredKey()).toBe("");
    setStoredKey("secret-value");
    expect(getStoredKey()).toBe("secret-value");
    forgetKey();
    expect(getStoredKey()).toBe("");
  });
});
