// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useTranslation } from "react-i18next";
import { usePangaeaWaterMeta } from "./usePangaeaWaterMeta";

/** Which published version is on the map, and how many source rows it cannot draw.
 *  Renders nothing until the meta endpoint answers — absent is honest, a guess is not. */
export function PangaeaVersionNote({ layerId }: { layerId: string }) {
  const { t } = useTranslation(["panels"]);
  const v = usePangaeaWaterMeta(layerId);
  if (!v) return null;
  return (
    <p className="text-white/75 text-[13px] leading-[1.5] mb-2 font-mono">
      {t("pangaeaWater.version", { date: v.date_published ?? "—", sha: v.sha256.slice(0, 12) })}
      {v.rows_unmappable > 0 && <> · {t("pangaeaWater.unmappable", { count: v.rows_unmappable })}</>}
    </p>
  );
}
