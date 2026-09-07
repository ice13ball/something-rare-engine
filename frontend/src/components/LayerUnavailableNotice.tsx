// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useTranslation } from "react-i18next";

interface Props {
  layers: string[];
  onDismiss: () => void;
  onRetry?: () => void;
}

export function LayerUnavailableNotice({ layers, onDismiss, onRetry }: Props) {
  const { t } = useTranslation("common");
  if (layers.length === 0) return null;

  return (
    <div role="alert" className="absolute bottom-6 left-1/2 -translate-x-1/2 z-overlay w-80 max-w-[calc(100vw-2rem)] bg-surface-primary border border-yellow-500/30 rounded-xl shadow-2xl px-4 py-3">
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <p className="text-yellow-400 text-[13px] font-semibold uppercase tracking-wider mb-1">
            {t("layerUnavailable.title")}
          </p>
          <ul className="space-y-0.5">
            {layers.map(name => (
              <li key={name} className="text-white/75 text-[13px] flex items-center gap-1.5">
                <span className="w-1 h-1 rounded-full bg-yellow-500/60 shrink-0" />
                {name}
              </li>
            ))}
          </ul>
          <div className="flex items-center gap-3 mt-2">
            <button
              onClick={onRetry ?? (() => window.location.reload())}
              className="text-yellow-400/80 hover:text-yellow-300 text-xs font-medium transition-colors"
            >
              {t("actions.retry")}
            </button>
            <span className="text-white/45 text-xs">·</span>
            <p className="text-white/65 text-xs">{t("layerUnavailable.otherLayersOperational")}</p>
          </div>
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
