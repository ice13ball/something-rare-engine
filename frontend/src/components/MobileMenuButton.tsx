// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { clearStoredConsent } from "../utils/analytics";

/**
 * Mobile-only "more" menu — visible at top-left below the `sm` breakpoint.
 * Replaces the bottom FooterLinks bar (which doesn't fit on narrow viewports
 * and overlaps the Layers button). Tapping opens a bottom-sheet listing the
 * same eight links the desktop bar shows. Hidden on ≥ 640 px so desktop UX
 * is untouched.
 */
export function MobileMenuButton({
  onReopenConsent,
  onOpenFeedback,
}: {
  onReopenConsent?: () => void;
  onOpenFeedback?: () => void;
}) {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  const close = () => setOpen(false);

  return (
    <div className="sm:hidden">
      <button
        onClick={() => setOpen(true)}
        aria-label="Open site menu"
        className="fixed top-4 left-4 z-panel min-h-[44px] min-w-[44px] flex items-center justify-center bg-[rgba(10,14,20,0.92)] border border-white/[0.08] text-white/80 hover:text-white text-lg rounded transition-colors"
      >
        <span aria-hidden="true">⋯</span>
      </button>

      {open && (
        <div className="fixed inset-0 z-overlay">
          <div className="absolute inset-0 bg-black/40" onClick={close} />
          <div className="absolute bottom-0 left-0 right-0 max-h-[75vh] bg-[rgba(10,14,20,0.97)] border-t border-white/[0.08] rounded-t-lg flex flex-col overflow-hidden animate-slide-up">
            <div className="flex justify-center pt-2 pb-1 shrink-0">
              <div className="w-8 h-1 rounded-full bg-white/20" />
            </div>
            <div className="flex items-center justify-between px-4 py-2 shrink-0 border-b border-white/[0.06]">
              <p className="text-white/80 text-xs font-mono uppercase tracking-wider">Menu</p>
              <button
                onClick={close}
                aria-label="Close menu"
                className="text-white/65 hover:text-white/90 text-xl leading-none w-8 h-8 flex items-center justify-center transition-colors"
              >
                ×
              </button>
            </div>
            <nav className="overflow-y-auto divide-y divide-white/[0.06]">
              <Link to="/blog"          onClick={close} className="block px-4 py-3 text-white/85 hover:text-white text-sm">Blog</Link>
              <Link to="/about"         onClick={close} className="block px-4 py-3 text-white/85 hover:text-white text-sm">About</Link>
              {onOpenFeedback && (
                <button
                  onClick={() => { onOpenFeedback(); close(); }}
                  className="block w-full text-left px-4 py-3 text-white/85 hover:text-white text-sm"
                >
                  Feedback
                </button>
              )}
              <Link to="/privacy"       onClick={close} className="block px-4 py-3 text-white/85 hover:text-white text-sm">Privacy</Link>
              <Link to="/terms"         onClick={close} className="block px-4 py-3 text-white/85 hover:text-white text-sm">Terms</Link>
              <Link to="/about#citation" onClick={close} className="block px-4 py-3 text-white/85 hover:text-white text-sm">Cite</Link>
              {onReopenConsent && (
                <button
                  onClick={() => { clearStoredConsent(); onReopenConsent(); close(); }}
                  className="block w-full text-left px-4 py-3 text-white/85 hover:text-white text-sm"
                >
                  Cookie Settings
                </button>
              )}
            </nav>
          </div>
        </div>
      )}
    </div>
  );
}
