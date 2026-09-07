// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useTranslation } from "react-i18next";
import { tEnum } from "../../../utils/translateEnum";
import { SEABED_CLASSES } from "../../../utils/seabedClasses";
import { WarningBanner } from "../shared/primitives";

// ── Seabed substrate panel ────────────────────────────────────────────────────

export function SeabedSubstratePanel({ feature }: { feature: any }) {
  const { t } = useTranslation(["panels", "enums"]);
  const p = feature.properties || {};
  const code: number | null = p.class_code ?? null;
  const cls = code != null ? SEABED_CLASSES[code] : undefined;
  const rgb = cls ? `rgb(${cls.rgb.join(",")})` : "transparent";
  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-2">
        <span className="inline-block w-4 h-4 rounded-sm border border-white/30" style={{ background: rgb }} />
        <span className="text-white font-medium">
          {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
          {code != null ? tEnum(t, "seabedSubstrate" as any, p.class_key) : t("panels:seabed.noData")}
        </span>
      </div>
      {code != null && (
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        <p className="text-sm text-white/70">{(t as any)(`panels:seabed.gloss.${p.class_key}`)}</p>
      )}
      {p.lat != null && (
        <p className="text-xs text-white/50 font-mono">{Number(p.lat).toFixed(3)}, {Number(p.lon).toFixed(3)}</p>
      )}
      <WarningBanner>{t("panels:seabed.licenseBadge")}</WarningBanner>
      <p className="text-xs text-white/50">{t("panels:seabed.caveat")}</p>
      <p className="text-xs text-white/40">
        {t("panels:seabed.citation")}{" "}
        <a className="text-cyan-400" href="https://www.earthbyte.org/seafloor-lithology-of-the-ocean-basins/"
           target="_blank" rel="noreferrer">EarthByte</a>
      </p>
    </div>
  );
}
