// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

/**
 * Says out loud that a link named an object this map could not produce.
 *
 * ⛔ Exists because the alternative was silence. `?focus=` has always read
 * `if (found) { open it }` and cleared the param either way, so a link to a
 * vent that has since been renamed turned its layer on, opened nothing, and
 * said nothing — and the reader concluded that was what the sender meant. A
 * link that is wrong and looks right is the failure this codebase treats as
 * worse than no feature at all.
 *
 * ⛔ Deliberately NOT `LayerUnavailableNotice`, which sits bottom-centre and
 * offers "Retry". That one is about a source failing to LOAD; retrying is the
 * right remedy there and a useless one here — refreshing will not bring back a
 * record the upstream removed. Sharing its instance would also print a false
 * cause, and sharing its screen slot would stack two unrelated complaints on
 * top of each other.
 */
import { useTranslation } from "react-i18next";

import { LAYER_LABEL_MAP, dashToCamel } from "./controls/tooltips";
import type { SharePanelFailure } from "../store/mapStore";

interface Props {
  failures: SharePanelFailure[];
  onDismiss: () => void;
}

export function FocusUnavailableNotice({ failures, onDismiss }: Props) {
  const { t } = useTranslation("common");
  const { t: tp } = useTranslation("panels");
  if (failures.length === 0) return null;

  // The left-menu toggle label is the one string for a layer that is genuinely
  // translated in all four locales; LAYER_LABEL_MAP is the English fallback for
  // anything the menu does not carry.
  const layerName = (id: string) =>
    (tp(`layers.${dashToCamel(id)}.toggle`, { defaultValue: "" }) as string) ||
    LAYER_LABEL_MAP[id] ||
    id;

  const anyRegenerates = failures.some(f => f.idRegenerates);

  return (
    <div
      // ⚠️ `polite`, not `assertive`: this arrives on page load, when a screen
      // reader is already announcing the map. It is worth saying, not worth
      // interrupting.
      role="status"
      aria-live="polite"
      className="absolute bottom-6 left-6 z-overlay w-80 max-w-[calc(100vw-2rem)] bg-surface-primary border border-sky-500/30 rounded-xl shadow-2xl px-4 py-3"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <p className="text-sky-300 text-[13px] font-semibold uppercase tracking-wider mb-1">
            {t("focusUnavailable.title")}
          </p>
          <p className="text-white/75 text-[13px] mb-1.5">{t("focusUnavailable.body")}</p>
          <ul className="space-y-0.5">
            {failures.map(f => (
              <li
                key={`${f.layerId} ${f.featureId}`}
                className="text-white/65 text-xs flex items-center gap-1.5"
              >
                <span className="w-1 h-1 rounded-full bg-sky-400/60 shrink-0" />
                <span className="truncate">
                  {/* An untyped `?focus=<value>` names no layer — it is searched
                      across several. Show the identifier alone rather than a
                      dangling separator that implies a layer we do not know. */}
                  {f.layerId ? <>{layerName(f.layerId)} · </> : null}
                  <span className="font-mono">{f.featureId}</span>
                </span>
              </li>
            ))}
          </ul>
          {anyRegenerates && (
            <p className="text-white/55 text-xs mt-2">{t("focusUnavailable.staleId")}</p>
          )}
        </div>
        <button
          onClick={onDismiss}
          className="text-white/60 hover:text-white text-base leading-none transition-colors shrink-0 p-1 min-w-[44px] min-h-[44px] flex items-center justify-center"
          aria-label={t("tooltips.dismiss")}
        >
          ×
        </button>
      </div>
    </div>
  );
}
