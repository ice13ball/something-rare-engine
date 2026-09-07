// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useState, useEffect, useRef, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { useMapStore } from "../store/mapStore";

const STORAGE_KEY = "abyssal_tutorial";
const RESHOW_DAYS = 30;

interface TutorialState {
  completed: boolean;
  completedAt?: number;
  currentStep: number;
}

function loadState(): TutorialState {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return { completed: false, currentStep: 0 };
    const s = JSON.parse(raw) as TutorialState;
    // Re-show after 30 days
    if (s.completed && s.completedAt && Date.now() - s.completedAt > RESHOW_DAYS * 86_400_000) {
      return { completed: false, currentStep: 0 };
    }
    return s;
  } catch {
    return { completed: false, currentStep: 0 };
  }
}

function saveState(s: TutorialState) {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(s)); } catch {}
}

const STEP_KEYS = ["step1", "step2", "step3", "step4"] as const;

const STEP_TARGETS: (string | null)[] = [
  null,
  "[data-tutorial='layers-panel']",
  "[data-tutorial='locate-btn']",
  "[data-tutorial='legend-btn']",
];

export function TutorialCoach() {
  const { t } = useTranslation("tutorial");
  const tutorialReady = useMapStore(s => s.tutorialReady);
  const [state, setState] = useState(loadState);
  const [step, setStep] = useState(state.currentStep);
  const [spotRect, setSpotRect] = useState<DOMRect | null>(null);

  // Track initial values for auto-advance detection
  const initialLayerSize = useRef<number | null>(null);

  const dismiss = useCallback(() => {
    const next: TutorialState = { completed: true, completedAt: Date.now(), currentStep: step };
    setState(next);
    saveState(next);
  }, [step]);

  const advance = useCallback(() => {
    if (step < STEP_KEYS.length - 1) {
      const nextStep = step + 1;
      setStep(nextStep);
      const s = { completed: false, currentStep: nextStep };
      setState(s);
      saveState(s);
    } else {
      dismiss();
    }
  }, [step, dismiss]);

  // Auto-advance step 0: user clicked a feature (selectedFeatures populated)
  useEffect(() => {
    if (step !== 0 || state.completed) return;
    return useMapStore.subscribe(s => {
      if (s.selectedFeatures.length > 0) advance();
    });
  }, [step, state.completed, advance]);

  // Auto-advance step 1: user toggled a layer (activeLayers size changed)
  useEffect(() => {
    if (step !== 1 || state.completed) return;
    // Capture initial size on step entry
    initialLayerSize.current = useMapStore.getState().activeLayers.size;
    return useMapStore.subscribe(s => {
      if (initialLayerSize.current !== null && s.activeLayers.size !== initialLayerSize.current) {
        advance();
      }
    });
  }, [step, state.completed, advance]);

  // Spotlight tracking — position a ring over the target element
  useEffect(() => {
    const selector = STEP_TARGETS[step];
    if (!selector) { setSpotRect(null); return; }

    let prevTop = 0, prevLeft = 0, prevW = 0, prevH = 0;
    const update = () => {
      const el = document.querySelector(selector);
      if (el) {
        const r = el.getBoundingClientRect();
        if (r.top !== prevTop || r.left !== prevLeft || r.width !== prevW || r.height !== prevH) {
          prevTop = r.top; prevLeft = r.left; prevW = r.width; prevH = r.height;
          setSpotRect(r);
        }
      } else {
        if (prevW !== 0) { prevTop = prevLeft = prevW = prevH = 0; setSpotRect(null); }
      }
    };

    // Initial position
    update();

    // Watch for size changes on the target
    const el = document.querySelector(selector);
    const ro = new ResizeObserver(update);
    if (el) ro.observe(el);

    // Watch for scroll/resize which move the element without resizing it
    window.addEventListener("scroll", update, { passive: true, capture: true });
    window.addEventListener("resize", update, { passive: true });

    return () => {
      ro.disconnect();
      window.removeEventListener("scroll", update, true);
      window.removeEventListener("resize", update);
    };
  }, [step]);

  // Don't render if completed, not ready, or no steps
  if (state.completed || !tutorialReady) return null;

  const isLast = step === STEP_KEYS.length - 1;
  const currentKey = STEP_KEYS[step];

  return (
    <>
      {/* Spotlight ring */}
      {spotRect && (
        <div
          className="fixed pointer-events-none z-tutorial-ring rounded-lg"
          style={{
            top: spotRect.top - 4,
            left: spotRect.left - 4,
            width: spotRect.width + 8,
            height: spotRect.height + 8,
            boxShadow: "0 0 0 2px rgba(0, 242, 255, 0.5), 0 0 12px 2px rgba(0, 242, 255, 0.25)",
            animation: "tutorial-pulse 2s ease-in-out infinite",
          }}
        />
      )}

      {/* Coach bar */}
      <div className="fixed bottom-20 sm:bottom-6 left-1/2 -translate-x-1/2 z-tutorial-bar w-[calc(100%-2rem)] sm:w-auto sm:min-w-[420px] sm:max-w-lg bg-surface-primary border border-white/15 rounded-xl px-5 py-3 flex items-center gap-4 shadow-2xl">
        {/* Step dots + mono counter (language-neutral, instrument style) */}
        <div className="flex flex-col items-center gap-1 shrink-0">
          <div className="flex gap-1.5">
            {STEP_KEYS.map((_, i) => (
              <div
                key={i}
                className={`w-2 h-2 rounded-full transition-colors ${
                  i < step ? "bg-white/70" : i === step ? "bg-white/90 ring-2 ring-white/20" : "border border-white/20"
                }`}
              />
            ))}
          </div>
          <span className="text-white/60 text-[9px] font-mono tracking-widest tabular-nums">
            {String(step + 1).padStart(2, "0")}/{String(STEP_KEYS.length).padStart(2, "0")}
          </span>
        </div>

        {/* Text */}
        <div className="flex-1 min-w-0">
          <p className="text-white text-sm font-medium">{t(`coach.${currentKey}.title`)}</p>
          <p className="text-white/65 text-xs leading-snug hidden sm:block">{t(`coach.${currentKey}.body`)}</p>
        </div>

        {/* Actions */}
        <div className="flex items-center gap-2 shrink-0">
          <button
            onClick={advance}
            className="bg-white/10 hover:bg-white/15 border border-white/20 text-white/90 text-xs px-3 py-1.5 rounded-md transition-colors"
          >
            {isLast ? t("coach.done") : t("coach.next")}
          </button>
          <button
            onClick={dismiss}
            className="text-white/70 hover:text-white/85 text-xs transition-colors"
          >
            {t("coach.skip")}
          </button>
        </div>
      </div>

    </>
  );
}
