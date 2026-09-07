// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { clearStoredConsent } from "../utils/analytics";
import { useMapStore } from "../store/mapStore";

export function FooterLinks({ onReopenConsent, onOpenFeedback }: { onReopenConsent?: () => void; onOpenFeedback?: () => void }) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const { t } = useTranslation("panels");
  const setExportPanelOpen = useMapStore((s) => s.setExportPanelOpen);
  return (
    <div className="hidden fixed bottom-2 left-1/2 -translate-x-1/2 z-10 sm:flex items-center gap-3 pointer-events-auto bg-surface-dim rounded-full px-4 py-1">
      <Link
        to="/blog"
        className="text-white/80 hover:text-white/90 text-xs transition-colors font-medium"
      >
        Blog
      </Link>
      <span className="text-white/60 text-xs">·</span>
      <Link to="/about" className="text-white/80 hover:text-white/90 text-xs transition-colors">
        About
      </Link>
      <span className="text-white/60 text-xs" aria-hidden="true">·</span>
      <Link to="/api-docs" className="text-white/80 hover:text-white/90 text-xs transition-colors">
        API
      </Link>
      <span className="text-white/60 text-xs" aria-hidden="true">·</span>
      <button
        onClick={() => setExportPanelOpen(true)}
        className="text-white/80 hover:text-white/90 text-xs transition-colors"
      >
        {(t as any)("export.opener")}
      </button>
      <span className="text-white/60 text-xs" aria-hidden="true">·</span>
      {onOpenFeedback && (
        <>
          <button
            onClick={onOpenFeedback}
            className="text-white/80 hover:text-white/90 text-xs transition-colors"
          >
            Feedback
          </button>
          <span className="text-white/60 text-xs" aria-hidden="true">·</span>
        </>
      )}
      <Link to="/privacy" className="text-white/80 hover:text-white/90 text-xs transition-colors">
        Privacy
      </Link>
      <span className="text-white/60 text-xs" aria-hidden="true">·</span>
      <Link to="/terms" className="text-white/80 hover:text-white/90 text-xs transition-colors">
        Terms
      </Link>
      <span className="text-white/60 text-xs" aria-hidden="true">·</span>
      <Link to="/about#citation" className="text-white/80 hover:text-white/90 text-xs transition-colors">
        Cite
      </Link>
      <span className="text-white/60 text-xs" aria-hidden="true">·</span>
      <a
        href="https://github.com/ice13ball/something-rare-engine"
        target="_blank"
        rel="noopener noreferrer"
        className="text-white/80 hover:text-white/90 text-xs transition-colors"
        title="Source code — AGPL-3.0-or-later"
      >
        Source
      </a>
      <span className="text-white/60 text-xs" aria-hidden="true">·</span>
      <Link to="/terms#source-code-licence" className="text-white/80 hover:text-white/90 text-xs transition-colors">
        AGPL-3.0
      </Link>
      {onReopenConsent && (
        <>
          <span className="text-white/60 text-xs" aria-hidden="true">·</span>
          <button
            onClick={() => { clearStoredConsent(); onReopenConsent(); }}
            className="text-white/80 hover:text-white/90 text-xs transition-colors"
          >
            Cookie Settings
          </button>
        </>
      )}
    </div>
  );
}
