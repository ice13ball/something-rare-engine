// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { toolsUrl } from "../utils/toolsLink";
import { useMapStore } from "../store/mapStore";
import { getLiveMapState } from "../utils/liveMapState";
import { openObjectsFor } from "./map3d/openFromLink";
import { pointObjectsFor } from "./map3d/pointFromLink";
import { collectShareableFilters } from "../types/filterRegistry";
import { collectShareableDisplay } from "../types/displayRegistry";
import { buildShareUrl } from "../utils/shareState";

export function FooterLinks({ onReopenConsent, onOpenFeedback }: { onReopenConsent?: () => void; onOpenFeedback?: () => void }) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const { t } = useTranslation("panels");
  // Site-chrome labels live in common.json; i18n.resolvedLanguage re-renders the Tools href on a switch.
  const { t: tc, i18n } = useTranslation("common");
  const setExportPanelOpen = useMapStore((s) => s.setExportPanelOpen);
  const [shareNote, setShareNote] = useState<string | null>(null);

  // ⛔ Reads the camera from the live publisher, not from localStorage: that one
  // is written on a debounce, so a link built from it would carry wherever the
  // map was a moment ago — wrong in a way the sender cannot see.
  const shareView = async () => {
    const live = getLiveMapState();
    if (!live) return;
    const vs = live.viewState as Record<string, number>;
    const url = buildShareUrl(window.location.origin, window.location.pathname, {
      camera: {
        longitude: vs.longitude, latitude: vs.latitude, zoom: vs.zoom,
        pitch: vs.pitch ?? 0, bearing: vs.bearing ?? 0,
      },
      layers: [...live.activeLayers],
      filters: collectShareableFilters(useMapStore.getState()),
      // ⛔ The button must carry what the address bar carries. When this field
      // was optional the two disagreed: the URL had the reader's open panel,
      // a link copied from the button did not.
      openObjects: openObjectsFor(useMapStore.getState().selectedFeatures),
      points: pointObjectsFor(useMapStore.getState().selectedFeatures),
      display: collectShareableDisplay(useMapStore.getState()),
    });
    try {
      await navigator.clipboard.writeText(url);
      setShareNote((t as any)("share.copied"));
    } catch {
      // Clipboard access is refused in some contexts. Say so rather than
      // leaving the user believing they have a link on the clipboard.
      setShareNote((t as any)("share.failed"));
    }
    setTimeout(() => setShareNote(null), 2500);
  };

  return (
    // left-1/2 caps the box at about half the viewport; a one-line w-max bar
    // covered the status line and the map attribution. Below ~1600 px it needs two rows,
    // so wrap whole items, never mid-label ("Share / view").
    <div className="hidden fixed bottom-2 left-1/2 -translate-x-1/2 z-10 sm:flex flex-wrap justify-center items-center gap-x-3 whitespace-nowrap pointer-events-auto bg-surface-dim rounded-full px-4 py-1">
      <Link
        to="/blog"
        className="text-white/80 hover:text-white/90 text-xs transition-colors font-medium"
      >
        {tc("site.footer.blog")}
      </Link>
      <span className="text-white/60 text-xs">·</span>
      <Link to="/about" className="text-white/80 hover:text-white/90 text-xs transition-colors">
        {tc("site.footer.about")}
      </Link>
      <span className="text-white/60 text-xs" aria-hidden="true">·</span>
      <Link to="/api-docs" className="text-white/80 hover:text-white/90 text-xs transition-colors">
        {tc("site.footer.api")}
      </Link>
      <span className="text-white/60 text-xs" aria-hidden="true">·</span>
      <a
        href={toolsUrl(i18n.resolvedLanguage)}
        className="text-white/80 hover:text-white/90 text-xs transition-colors"
        title={tc("site.footer.toolsHint")}
      >
        {tc("site.footer.tools")}
      </a>
      <span className="text-white/60 text-xs" aria-hidden="true">·</span>
      <button
        onClick={() => setExportPanelOpen(true)}
        className="text-white/80 hover:text-white/90 text-xs transition-colors"
      >
        {(t as any)("export.opener")}
      </button>
      <span className="text-white/60 text-xs" aria-hidden="true">·</span>
      <button
        onClick={shareView}
        className="text-white/80 hover:text-white/90 text-xs transition-colors"
      >
        {shareNote ?? (t as any)("share.opener")}
      </button>
      <span className="text-white/60 text-xs" aria-hidden="true">·</span>
      {onOpenFeedback && (
        <>
          <button
            onClick={onOpenFeedback}
            className="text-white/80 hover:text-white/90 text-xs transition-colors"
          >
            {tc("site.footer.feedback")}
          </button>
          <span className="text-white/60 text-xs" aria-hidden="true">·</span>
        </>
      )}
      <Link to="/privacy" className="text-white/80 hover:text-white/90 text-xs transition-colors">
        {tc("site.footer.privacy")}
      </Link>
      <span className="text-white/60 text-xs" aria-hidden="true">·</span>
      <Link to="/terms" className="text-white/80 hover:text-white/90 text-xs transition-colors">
        {tc("site.footer.terms")}
      </Link>
      <span className="text-white/60 text-xs" aria-hidden="true">·</span>
      <Link to="/about#citation" className="text-white/80 hover:text-white/90 text-xs transition-colors">
        {tc("site.footer.cite")}
      </Link>
      <span className="text-white/60 text-xs" aria-hidden="true">·</span>
      <a
        href="https://github.com/ice13ball/something-rare-engine"
        target="_blank"
        rel="noopener noreferrer"
        className="text-white/80 hover:text-white/90 text-xs transition-colors"
        title={tc("site.footer.sourceTitle")}
      >
        {tc("site.footer.source")}
      </a>
      <span className="text-white/60 text-xs" aria-hidden="true">·</span>
      <Link to="/terms#source-code-licence" className="text-white/80 hover:text-white/90 text-xs transition-colors">
        AGPL-3.0
      </Link>
      {onReopenConsent && (
        <>
          <span className="text-white/60 text-xs" aria-hidden="true">·</span>
          <button
            onClick={onReopenConsent}
            className="text-white/80 hover:text-white/90 text-xs transition-colors"
          >
            {tc("site.footer.cookieSettings")}
          </button>
        </>
      )}
    </div>
  );
}
