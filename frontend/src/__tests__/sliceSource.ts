// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// Cutting one function out of a source file, for the tests that assert on the
// SHAPE of code rather than its behaviour.
//
// Two things this exists to prevent, both found 2026-09-12:
//
// 1. ⛔ `src.indexOf("\n}\n")` returns -1 on a CRLF checkout, and -1 fed to
//    `slice(start, -1)` does not fail — it silently returns everything from
//    `start` to one character before the END OF FILE. The assertion then counts
//    matches across the whole file while claiming to count them in one
//    function. Node's `readFileSync(..., "utf-8")` hands back the bytes as they
//    are, so a Windows clone hits this immediately. (Python is immune: its text
//    mode translates CRLF to LF before you ever see it — that is why only the
//    TypeScript tests needed this.)
//
// 2. A marker that stops matching after a refactor degrades the same way. So
//    this throws rather than returning a wrong answer: a test that can no
//    longer find what it measures must go red, never quietly measure something
//    else.
//
// Guarded by `source-slicing-survives-crlf.test.ts`.

/** Normalise CRLF and lone CR to LF, so every anchor below is newline-agnostic. */
export function toLf(src: string): string {
  return src.replace(/\r\n?/g, "\n");
}

/**
 * The text from `signature` up to (not including) the line that closes it at
 * column 0 — i.e. the body of a top-level function.
 *
 * @throws if the signature is absent, or if no closing brace follows it.
 */
export function sliceFunctionBody(src: string, signature: string): string {
  const text = toLf(src);
  const start = text.indexOf(signature);
  if (start === -1) {
    throw new Error(`sliceFunctionBody: signature not found: ${signature}`);
  }
  const end = text.indexOf("\n}\n", start);
  if (end === -1) {
    throw new Error(
      `sliceFunctionBody: no top-level closing brace after ${signature} — ` +
        "refusing to return a slice that runs to the end of the file",
    );
  }
  return text.slice(start, end);
}
