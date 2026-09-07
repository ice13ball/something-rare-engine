// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import type { ClaimDossierV2Data } from "../ImpactReportV2";

export function ClaimDossierV2({ dossier }: { dossier: ClaimDossierV2Data }) {
  const c = dossier.claim;
  return (
    <article className="border border-white/10 rounded p-4">
      <header className="flex justify-between items-baseline gap-3">
        <h3 className="text-white">
          <span className="font-semibold">{c.concession_id}</span>
          <span className="text-white/80 font-normal"> · {c.contractor_name}</span>
        </h3>
        <span className="font-mono text-white/90">{dossier.min_distance_km} km</span>
      </header>

      <dl className="mt-2 grid grid-cols-2 gap-x-6 gap-y-1 text-sm text-white/85">
        <dt>Attributed measurements</dt>
        <dd className="font-mono text-white/95">{dossier.attributed_measurement_count}</dd>

        <dt>Attributed plume backtracks</dt>
        <dd className="font-mono text-white/95">{dossier.attributed_plume_count}</dd>

        <dt>Profiles within 50 km</dt>
        <dd className="font-mono text-white/95">{dossier.profiles_within_50km}</dd>

        {c.area_km2 != null && (
          <>
            <dt>Concession area</dt>
            <dd className="font-mono text-white/95">{c.area_km2.toLocaleString()} km²</dd>
          </>
        )}
      </dl>
    </article>
  );
}
