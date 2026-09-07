// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useTranslation } from "react-i18next";
import { useMapStore } from "../store/mapStore";

export function ExportToolbar() {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const { t } = useTranslation("panels");
  const te = (k: string) => (t as any)(`export.${k}`);
  const mode = useMapStore((s) => s.selectionMode);
  const setMode = useMapStore((s) => s.setSelectionMode);
  const clear = useMapStore((s) => s.clearAoiSelection);
  const open = useMapStore((s) => s.exportPanelOpen);
  if (!open) return null;

  const Btn = ({ m, tKey }: { m: "box" | "polygon" | "hexes"; tKey: string }) => (
    <button
      onClick={() => setMode(mode === m ? null : m)}
      className={`px-2 py-1 rounded text-xs ${
        mode === m
          ? "bg-white/20 text-white"
          : "bg-white/5 text-white/70 hover:bg-white/10"
      }`}
    >
      {te(tKey)}
    </button>
  );

  const hint =
    mode === "box"     ? te("hintBox") :
    mode === "polygon" ? te("hintPolygon") :
    mode === "hexes"   ? te("hintHexes") :
    null;

  return (
    <div className="absolute top-4 left-1/2 -translate-x-1/2 z-overlay flex flex-col items-center gap-1 pointer-events-auto">
      <div className="flex gap-1 bg-[#0d1117]/90 border border-white/10 rounded-lg p-1">
        <Btn m="box" tKey="box" />
        <Btn m="polygon" tKey="polygon" />
        <Btn m="hexes" tKey="hexes" />
        <button
          onClick={clear}
          className="px-2 py-1 rounded text-xs bg-white/5 text-white/70 hover:bg-white/10"
        >
          {te("clear")}
        </button>
      </div>
      {hint && (
        <div className="text-xs text-white/60 bg-[#0d1117]/80 px-3 py-1 rounded-lg border border-white/10">
          {hint}
        </div>
      )}
    </div>
  );
}
