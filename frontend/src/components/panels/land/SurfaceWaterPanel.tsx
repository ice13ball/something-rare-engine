// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useTranslation } from "react-i18next";
import { Badge, PanelHeader, Section, SourceAttribution } from "../shared/primitives";
import { sourceLinkFor } from "../../../utils/sourceUrl";

export function SurfaceWaterPanel() {
  const { t } = useTranslation("panels");
  return (
    <>
      <Badge label={t("surfaceWater.panelBadge")} color="text-cyan-300 border-cyan-500/40" />
      <PanelHeader>{t("surfaceWater.panelTitle")}</PanelHeader>
      <Section title={t("surfaceWater.aboutSectionTitle")}>
        <p className="text-white/70 text-xs leading-relaxed">
          Water occurrence frequency 1984–2021 at 30m resolution. Blue = permanent water, lighter = seasonal.
          Raster layer — click individual features on other layers for details.
        </p>
      </Section>
      <SourceAttribution link={sourceLinkFor("jrc-surface-water", {})} />
    </>
  );
}

