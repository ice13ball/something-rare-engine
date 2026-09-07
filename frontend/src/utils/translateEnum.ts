// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

/**
 * Translate an enumerated value using the enums namespace.
 *
 * Falls back to the raw value if the enum group/value isn't in enums.json
 * — handles upstream registries adding new values we haven't translated yet.
 *
 * Accepts `unknown` for `t` to stay compatible with both single-namespace
 * and multi-namespace TFunction instances from useTranslation(). The cast
 * to `any` is intentional — i18next's overloaded TFunction generics cause
 * TS2589 "excessively deep" inference when passed as a typed parameter.
 *
 * @param t        - the t() function from useTranslation()
 * @param group    - enum group ("status" | "resourceType" | "oceanBasin" | "offshoreType" | "seamountSize")
 * @param value    - source-language value; null/undefined returns "—"
 */
export function tEnum(
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  t: any,
  group: "status" | "resourceType" | "oceanBasin" | "offshoreType" | "seamountSize" | "iso_topic",
  value: string | null | undefined,
): string {
  if (value == null || value === "") return "—";
  // eslint-disable-next-line @typescript-eslint/no-unsafe-call
  return (t(`${group}.${value}`, { ns: "enums", defaultValue: value }) as string) ?? value;
}
