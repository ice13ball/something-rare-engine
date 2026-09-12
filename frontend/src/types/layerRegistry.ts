// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import type { LayerId } from "./layers";

/**
 * Compile-time completeness guard for a per-layer registry.
 *
 * `Covered` is the union of LayerIds a registry actually lists — derive it from
 * the literal with `as const`, e.g. `(typeof SEARCH_CONFIGS)[number]["layerId"]`.
 * An array annotated `: SearchConfig[]` widens that field back to the whole
 * LayerId union and the guard silently passes, so the `as const satisfies`
 * form is load-bearing, not style. If `layerId` is optional and some entries
 * omit the key entirely (rather than carrying `layerId: undefined`), a plain
 * indexed access like `(typeof X)[number]["layerId"]` fails to compile — TS
 * refuses to index a union on a key some members lack. Use `LayerIdOf` below
 * instead; it distributes over the union so members without the key just
 * contribute `never`.
 *
 * `OptedOut` is the union the registry deliberately skips. Forcing an explicit
 * opt-out is the point: "this layer has no search" becomes a decision someone
 * wrote down, not an omission nobody noticed.
 *
 * When something is in neither set this resolves to the union of the missing
 * ids, so `const _x: AssertComplete<...> = true` fails with those ids named in
 * the error text.
 */
export type AssertComplete<Covered extends LayerId, OptedOut extends LayerId> =
  Exclude<LayerId, Covered | OptedOut> extends never
    ? true
    : Exclude<LayerId, Covered | OptedOut>;

/**
 * Compile-time disjointness guard for a per-layer registry and its opt-out list.
 *
 * `AssertComplete` only checks that `Covered | OptedOut` adds up to every
 * `LayerId` — it never checks that the two sets don't overlap. That leaves a
 * hole exactly where `AssertComplete` exists to prevent one: someone silences
 * the completeness error by adding a layer to the opt-out list, even though
 * the layer is already wired up and working in the registry. The opt-out list
 * then asserts something false about a layer that works — the same species of
 * lie as a false exclusion reason, just produced by a different mistake.
 *
 * Resolves to `true` when `A` and `B` share no id. Otherwise resolves to the
 * union of ids present in both, so `const _x: AssertDisjoint<...> = true`
 * fails with the offending id(s) named in the error text, the same way
 * `AssertComplete` names the missing ones.
 */
export type AssertDisjoint<A extends LayerId, B extends LayerId> =
  Extract<A, B> extends never
    ? true
    : Extract<A, B>;

/**
 * Extracts the `layerId` a registry entry carries, distributing over a union
 * of entry types. Needed whenever `layerId` is optional and at least one
 * union member omits the key outright (as opposed to declaring it and being
 * `undefined`) — see the note on `AssertComplete` above. Members lacking the
 * key contribute `never`, which drops out of the resulting union for free.
 */
export type LayerIdOf<S> = S extends { layerId: infer L extends LayerId } ? L : never;
