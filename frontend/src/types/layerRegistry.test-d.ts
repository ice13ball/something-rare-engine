// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import type { AssertComplete } from "./layerRegistry";

// A registry that covers exactly one id and opts out of nothing is INCOMPLETE.
// AssertComplete must therefore NOT be `true` here, so assigning true is an error.
// @ts-expect-error - incomplete registry must not satisfy the guard
export const _incompleteIsRejected: AssertComplete<"contracts", never> = true;

// Covering one id and opting out of every other id is COMPLETE.
type AllButContracts = Exclude<
  import("./layers").LayerId,
  "contracts"
>;
export const _completeIsAccepted: AssertComplete<"contracts", AllButContracts> = true;
