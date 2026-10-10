// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useEffect, useRef, useState, type MutableRefObject } from "react";
import {
  ARGO_FAILED_NAME, fileArgoDoc, mergeYearBounds, selectArgoDoc, touchArgoDepth, type ArgoOxygenDoc,
} from "../../utils/argoOxygenPoints";

export type FetchJsonGuarded = <T>(
  ref: MutableRefObject<boolean>, path: string, setter: (d: T) => void, name: string,
) => void;

/**
 * Per-depth BGC-Argo O₂ documents for Map3D (extracted so the wiring can be tested).
 *
 * - One one-shot latch per depth; the document is filed under ITS OWN depth (`doc.depth`), so a slow answer for
 *   another depth can never be drawn, and `selectArgoDoc` returns the selected depth's document only.
 * - Memory: the current depth and the last two visited stay decoded; older ones are evicted and their latch is
 *   released, so a revisit fetches them again.
 * - ⛔ A depth that is already loaded is never fetched again — "Retry" (which un-latches every guarded layer and
 *   gives `fetchJsonGuarded` a new identity) must not re-download the 2.6 MiB the map is already drawing.
 * - The year span is merged once per arriving document, so evicting a document does not move the year selects.
 */
export function useArgoOxygenDocs(drawing: boolean, depth: number, fetchJsonGuarded: FetchJsonGuarded) {
  const [docs, setDocs] = useState<Record<number, ArgoOxygenDoc>>({});
  const [bounds, setBounds] = useState<{ min: number; max: number } | null>(null);
  const docsRef = useRef(docs);
  const latches = useRef<Record<number, MutableRefObject<boolean>>>({});
  const recent = useRef<number[]>([]);

  useEffect(() => {
    if (!drawing) return;
    recent.current = touchArgoDepth(recent.current, depth);
    if (docs[depth]) return;
    const latch = (latches.current[depth] ??= { current: false });
    fetchJsonGuarded<ArgoOxygenDoc>(latch, `/api/v1/argo-oxygen/points/${depth}`, (d) => {
      const { docs: next, dropped } = fileArgoDoc(docsRef.current, d, recent.current);
      for (const gone of dropped) { const l = latches.current[gone]; if (l) l.current = false; }
      docsRef.current = next;
      setDocs(next);
      setBounds((prev) => mergeYearBounds(prev, d));
    }, ARGO_FAILED_NAME);
  }, [drawing, depth, docs, fetchJsonGuarded]);

  return { docs, doc: selectArgoDoc(docs, depth, drawing), bounds };
}
