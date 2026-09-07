// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

const KEY_MAP: Record<string, string> = {
  "Polymetallic Nodules": "nodules",
  "Cobalt-rich Ferromanganese Crusts": "crusts",
  "Polymetallic Sulphides": "sulphides",
};

/** Environmental impact description per resource type — consumed by panels/ocean/MiningPanel. */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function getResourceImpact(t: (key: string, opts?: any) => string, resourceType: string | null | undefined): string {
  if (!resourceType) return "";
  const subKey = KEY_MAP[resourceType];
  if (!subKey) return "";
  return t(`resourceImpact.${subKey}`, { ns: "panels" });
}
