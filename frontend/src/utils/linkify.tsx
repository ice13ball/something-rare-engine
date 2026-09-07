// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import React from "react";

// Split on http(s) URLs, keeping the URL as its own capture group so it can be
// rendered as an anchor. Stops at whitespace or angle brackets; trailing
// sentence punctuation is peeled off below so links end cleanly.
const URL_SPLIT = /(https?:\/\/[^\s<>]+)/g;
const IS_URL = /^https?:\/\//;
const TRAILING_PUNCT = /[.,;:)\]}'"!?]+$/;

/**
 * Render a string with embedded http(s) URLs turned into clickable links.
 * Used for free-text citation / attribution strings (e.g. PANGAEA DOIs) where
 * the URL lives inside prose rather than in a dedicated field.
 */
export function Linkify({ text, linkClassName }: { text: string; linkClassName?: string }) {
  const cls = linkClassName ?? "text-sky-400 hover:underline break-all";
  return (
    <>
      {text.split(URL_SPLIT).map((part, i) => {
        if (!IS_URL.test(part)) return <React.Fragment key={i}>{part}</React.Fragment>;
        const tail = part.match(TRAILING_PUNCT)?.[0] ?? "";
        const url = tail ? part.slice(0, -tail.length) : part;
        return (
          <React.Fragment key={i}>
            <a href={url} target="_blank" rel="noopener noreferrer" className={cls}>
              {url}
            </a>
            {tail}
          </React.Fragment>
        );
      })}
    </>
  );
}
