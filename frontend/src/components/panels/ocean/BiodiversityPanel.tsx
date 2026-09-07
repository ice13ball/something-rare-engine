// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useTranslation } from "react-i18next";
import { sourceLinkFor } from "../../../utils/sourceUrl";

import { T } from "../shared/tokens";
import { Row, Section, Subtitle, BodyText, WarningBanner, SourceAttribution, ExternalLink, ExternalLinks } from "../shared/primitives";

export function BiodiversityPanel({ properties: p }: { properties: Record<string, unknown> }) {
  const { t } = useTranslation("panels");
  return (
    <>
      <h2 className={`${T.header} italic`}>
        {String(p.scientific_name ?? "Unknown species")}
      </h2>
      {p.vernacular_name && (
        <Subtitle className="text-green-400 mb-3">{String(p.vernacular_name)}</Subtitle>
      )}

      {p.is_endangered && (
        <WarningBanner color="red">{t("biodiversity.endangeredWarning")}</WarningBanner>
      )}

      {p.image_url && (
        <div className="mb-3">
          <img src={String(p.image_url)} alt={String(p.scientific_name ?? "")}
            className="w-full rounded-lg object-cover max-h-36"
            onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
          />
        </div>
      )}

      <Section title={t("biodiversity.taxonomySectionTitle")}>
        {p.phylum     != null && <Row label={t("biodiversity.phylumLabel")} value={String(p.phylum)} />}
        {p.class_name != null && <Row label={t("biodiversity.classLabel")}  value={String(p.class_name)} />}
        {p.order_name != null && <Row label={t("biodiversity.orderLabel")}  value={String(p.order_name)} />}
        {p.family     != null && <Row label={t("biodiversity.familyLabel")} value={String(p.family)} />}
      </Section>

      {p.worms_verified === true && (
        <Section title={t("biodiversity.wormsSectionTitle")}>
          {p.valid_name != null && String(p.valid_name) !== String(p.scientific_name ?? "") && (
            <Row
              label={t("biodiversity.wormsValidNameLabel")}
              value={`${String(p.scientific_name)} → ${String(p.valid_name)}`}
            />
          )}
          {p.worms_is_marine === 1 && (
            <Row label={t("biodiversity.wormsEnvLabel")} value={t("biodiversity.wormsMarine")} />
          )}
          {p.aphia_id != null && (
            <Row label="AphiaID" value={String(p.aphia_id)} />
          )}
          {(() => {
            const raw = p.worms_url != null ? String(p.worms_url) : "";
            let safe: string | null = null;
            try {
              const u = new URL(raw);
              if ((u.protocol === "https:" || u.protocol === "http:") &&
                  (u.hostname === "marinespecies.org" || u.hostname.endsWith(".marinespecies.org"))) {
                safe = u.href;
              }
            } catch { /* not a valid absolute URL */ }
            return safe && (
              <a
                href={safe}
                target="_blank"
                rel="noopener noreferrer"
                className="text-cyan-400 text-[13px] underline"
              >
                {t("biodiversity.wormsLink")}
              </a>
            );
          })()}
          <p className="text-white/40 text-[11px] mt-2">{t("biodiversity.wormsCitation")}</p>
        </Section>
      )}

      {p.depth != null && (
        <Section title={t("biodiversity.observationSectionTitle")}>
          <Row label={t("biodiversity.depthLabel")} value={`${Number(p.depth).toFixed(0)} m`} />
        </Section>
      )}

      {p.description && (
        <BodyText className="text-white/70 border-t border-white/10 pt-3">
          {String(p.description)}
        </BodyText>
      )}
      {typeof p.obis_id === "string" && p.obis_id.length > 0 && (
        <ExternalLinks>
          <ExternalLink
            href={`https://obis.org/occurrence/${p.obis_id}`}
            label={t("biodiversity.verifyOnObis")}
          />
        </ExternalLinks>
      )}
      {/* Footer keeps the OBIS provenance/DOI citation (the AWS Open Data origin),
          distinct from the per-occurrence verify link above — pass {} so it
          resolves to the citation homepage, not the per-feature page. */}
      <SourceAttribution link={sourceLinkFor("obis-occurrence", {})} />
    </>
  );
}

