// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { getStoredConsent, updateConsent, analytics } from "../utils/analytics";

export function CookieBanner({ forceOpen, onClose }: { forceOpen?: boolean; onClose?: () => void }) {
  const [visible, setVisible] = useState(false);
  const { t } = useTranslation("common");

  useEffect(() => {
    if (forceOpen) { setVisible(true); return; }
    const stored = getStoredConsent();
    if (stored !== null) return;  // prior decision (shared cookie) exists — respect it
    // No decision yet: ask. Every visitor, wherever they are — there is no
    // automatic grant (until 2026-09-23 one was given by browser language).
    setVisible(true);
  }, [forceOpen]);

  if (!visible) return null;

  const handle = (granted: boolean) => {
    updateConsent(granted);
    analytics.consentDecision(granted);
    setVisible(false);
    // Cookie Settings keeps forceOpen true; tell the parent, or a second
    // reopen would find it already true and do nothing.
    onClose?.();
  };

  return (
    <div className="fixed bottom-0 left-0 right-0 z-[46] p-3 flex justify-center pointer-events-none">
      <div role="dialog" aria-label={t("cookie.label")} className="pointer-events-auto bg-surface-primary border border-white/15 rounded-xl px-4 py-3 max-w-2xl w-full shadow-2xl flex flex-col sm:flex-row items-start sm:items-center gap-3">
        <p className="text-white/80 text-xs leading-relaxed flex-1">
          {t("cookie.text")}{" "}
          <Link to="/privacy" className="text-white/85 hover:text-white underline">
            {t("cookie.privacy")}
          </Link>
        </p>
        <div className="flex gap-2 flex-shrink-0">
          <button
            onClick={() => handle(false)}
            className="px-3 py-1.5 text-xs text-white/70 hover:text-white border border-white/15 hover:border-white/30 rounded-lg transition-colors"
          >
            {t("cookie.decline")}
          </button>
          <button
            onClick={() => handle(true)}
            className="px-3 py-1.5 text-xs bg-white/90 hover:bg-white text-black font-medium rounded-lg transition-colors"
          >
            {t("cookie.accept")}
          </button>
        </div>
      </div>
    </div>
  );
}
