// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useTranslation } from "react-i18next";

import { Row, Section, PanelHeader, HintText } from "../shared/primitives";
import { usePangaeaWaterMeta } from "../shared/usePangaeaWaterMeta";
import { PangaeaCitationBlock } from "../shared/PangaeaCitationBlock";

/** The source's header string, used until meta arrives. ⛔ An areal RATE —
 *  carbon fixed under one square metre per day — never a concentration. */
const GPP_HEADER = "GPP C [mg/m**2/day]";

export function GreenlandPrimaryProductionPanel({ properties }: { properties: Record<string, unknown> }) {
  const { t } = useTranslation(["panels", "common"]);
  const meta = usePangaeaWaterMeta("greenland-primary-production");
  const unit = meta?.units?.gpp_c_mg_m2_day ?? GPP_HEADER;
  const gpp = typeof properties.gpp_c_mg_m2_day === "number" ? properties.gpp_c_mg_m2_day : null;
  return (
    <div>
      <PanelHeader>{String(properties.event ?? "")}</PanelHeader>
      {properties.event_2 != null && <HintText>{String(properties.event_2)}</HintText>}
      <Section title="GPP">
        <Row label={t("pangaeaWater.date")}
             value={properties.sample_date != null ? String(properties.sample_date) : t("pangaeaWater.noDateInSource")} />
        <Row label={unit} value={gpp ?? "—"} />
        <HintText>{t("pangaeaWater.gppRate")}</HintText>
      </Section>
      <PangaeaCitationBlock version={meta} doiFallback="10.1594/PANGAEA.965985" />
    </div>
  );
}
