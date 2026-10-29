// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useTranslation } from "react-i18next";
import { useMapStore } from "../../../store/mapStore";
import type { GraphicsMode } from "../../../utils/graphicsPreference";

const MODES: readonly GraphicsMode[] = ["enhanced", "simple"];

/** One shared setting, shown in the seamounts and the vents rows: enhanced 3D models or simple columns. */
export function GraphicsSwitch() {
  const { t } = useTranslation("panels");
  const graphicsMode = useMapStore((s) => s.graphicsMode);
  const setGraphicsMode = useMapStore((s) => s.setGraphicsMode);
  return (
    <div className="flex flex-col gap-1 pb-1">
      <span className="text-[11px] font-mono text-white/70 uppercase tracking-wide">{t("controls.fieldLayer.display")}</span>
      <div className="flex gap-1">
        {MODES.map((m) => (
          <button
            key={m}
            aria-pressed={graphicsMode === m}
            onClick={() => setGraphicsMode(m)}
            className={`flex-1 text-[12px] font-mono rounded px-2 py-1 border transition-colors ${graphicsMode === m ? "bg-cyan-400/20 border-cyan-400/50 text-cyan-300" : "bg-white/5 border-white/10 text-white/80 hover:bg-white/10"}`}
          >
            {t(`controls.graphics.${m}`)}
          </button>
        ))}
      </div>
      <span className="text-[10px] text-white/55 leading-snug">{t("controls.graphics.hint")}</span>
    </div>
  );
}
