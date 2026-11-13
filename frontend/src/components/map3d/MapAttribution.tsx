// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useEffect, useState, type ReactNode } from "react";

/**
 * The basemap's source credits as a compact "(i)" in the map's bottom-right corner (Michał 13.11:
 * the credit bar above the footer covered the map). Open on load, folded on the reader's first pan
 * or zoom or after FOLD_AFTER_MS, reopened by the "(i)" — the OSMF attribution guideline allows
 * exactly these. Where the open text goes: see the comment above the JSX.
 *
 * ⛔ Not MapLibre's own AttributionControl: under deck.gl the MapLibre container sits at
 * `z-index: -1` inside deck's view div, so its "(i)" and links render but cannot be clicked.
 * The text is read from the live style's sources, so credits edited on the basemap server
 * (`basemap.something-rare.com/styles/…`) arrive without a release.
 */

type MapLike = {
  getStyle?: () => { sources?: Record<string, { attribution?: string }> } | undefined;
  on?: (ev: string, fn: () => void) => void;
  off?: (ev: string, fn: () => void) => void;
};

/** Attribution HTML → text and http(s) links only; anything else in the string is dropped. */
function toNodes(html: string, key: string): ReactNode[] {
  const doc = new DOMParser().parseFromString(`<div>${html}</div>`, "text/html");
  const out: ReactNode[] = [];
  doc.body.firstChild?.childNodes.forEach((n, i) => {
    if (n.nodeType === Node.TEXT_NODE) out.push(n.textContent);
    else if (n instanceof HTMLAnchorElement && /^https?:\/\//.test(n.href)) {
      out.push(<a key={`${key}-${i}`} href={n.href} target="_blank" rel="noopener noreferrer">{n.textContent}</a>);
    } else if (n.textContent) out.push(n.textContent);
  });
  return out;
}

const FOLD_AFTER_MS = 8000;

export function MapAttribution({ getMap, folded }: { getMap: () => MapLike | null | undefined; folded: boolean }) {
  const [open, setOpen] = useState(true);
  const [credits, setCredits] = useState<string[]>([]);

  useEffect(() => { if (folded) setOpen(false); }, [folded]);
  // Counted from when the credits first show (the style has loaded), not from mount.
  const shown = credits.length > 0;
  useEffect(() => {
    if (!shown) return;
    const t = setTimeout(() => setOpen(false), FOLD_AFTER_MS);
    return () => clearTimeout(t);
  }, [shown]);

  useEffect(() => {
    let map: MapLike | null | undefined;
    let timer: ReturnType<typeof setInterval> | undefined;
    const read = () => {
      let sources: Record<string, { attribution?: string }> = {};
      try { sources = map?.getStyle?.()?.sources ?? {}; } catch { return; }  // style not parsed yet
      const seen = [...new Set(Object.values(sources).map(s => s.attribution?.trim()).filter(Boolean) as string[])];
      setCredits(prev => (prev.join("\n") === seen.join("\n") ? prev : seen));
    };
    // The map instance appears after ReactMap mounts; poll briefly for it, then follow style changes
    // (a language switch loads another style).
    timer = setInterval(() => {
      map = getMap();
      if (!map?.on) return;
      clearInterval(timer);
      // An inline style object (the legacy basemap) has already fired `styledata` by now, and
      // `isStyleLoaded()` stays false while any tile is pending, so read once right away too.
      map.on("styledata", read);
      read();
    }, 250);
    return () => { clearInterval(timer); map?.off?.("styledata", read); };
  }, [getMap]);

  if (credits.length === 0) return null;
  // The "i" sits in the very corner, under the "Discover" button. The open text must not cover
  // that button, the zoom buttons above it, or the centred footer bar (Michał 13.11, `map` review):
  // from 640 px it opens LEFT of that button column and ABOVE the footer bar, whose height grows to
  // ~80 px as it wraps on narrow screens (measured 640–1920 px); below 640 px there is no footer bar
  // and "Discover" moves to the top, so it opens left of the zoom buttons, beside the "i".
  return (
    <>
      {open && (
        <p
          className="absolute z-[21] bottom-2 right-16 sm:bottom-24 sm:right-[132px] pointer-events-auto rounded bg-black/60 px-2 py-1 text-[10px] leading-snug text-white/75 [&_a]:text-white/90 [&_a]:underline-offset-2 [&_a:hover]:underline"
          style={{ maxWidth: "min(330px, calc(100vw - 72px))" }}
        >
          {credits.map((c, i) => (
            <span key={i}>{i > 0 && " · "}{toNodes(c, String(i))}</span>
          ))}
        </p>
      )}
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        aria-label="Map attribution"
        aria-expanded={open}
        title="Map attribution"
        className="absolute z-[21] bottom-2 right-2 h-6 w-6 rounded-full bg-black/60 text-white/80 hover:text-white text-xs font-serif italic leading-6 text-center pointer-events-auto"
      >
        i
      </button>
    </>
  );
}
