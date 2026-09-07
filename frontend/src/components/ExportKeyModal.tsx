// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useState } from "react";
import { useTranslation } from "react-i18next";

const LS_KEY = "abyssal_export_key";
export const getStoredKey = () => localStorage.getItem(LS_KEY) ?? "";
export const setStoredKey = (k: string) => localStorage.setItem(LS_KEY, k);
export const forgetKey = () => localStorage.removeItem(LS_KEY);

export function ExportKeyModal({
  onSaved,
  onClose,
  onRequestKey,
}: {
  onSaved: (k: string) => void;
  onClose: () => void;
  onRequestKey: () => void;
}) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const { t } = useTranslation("panels");
  const te = (k: string) => (t as any)(`export.${k}`);
  const [val, setVal] = useState("");
  return (
    <div
      className="fixed inset-0 z-overlay flex items-center justify-center p-4"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="relative bg-[#0d1117] border border-white/10 rounded-xl shadow-2xl w-full max-w-md p-5 space-y-3">
        <p className="text-white/90 text-sm font-medium">
          {te("enterKey")}
        </p>
        <p className="text-white/60 text-xs">
          {te("keyModalSubtitle")}
        </p>
        <input
          value={val}
          onChange={(e) => setVal(e.target.value)}
          placeholder="ak_live_…"
          type="password"
          className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-xs text-white/90"
        />
        <button
          disabled={!val.trim()}
          onClick={() => {
            setStoredKey(val.trim());
            onSaved(val.trim());
          }}
          className="w-full py-2 rounded-lg bg-white/10 hover:bg-white/15 disabled:opacity-40 text-white/90 text-xs"
        >
          {te("saveAndDownload")}
        </button>
        <button
          onClick={onRequestKey}
          className="w-full text-cyan-400 hover:text-cyan-300 text-xs"
        >
          {te("requestKey")}
        </button>
      </div>
    </div>
  );
}
