// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { CompositeLayer } from "@deck.gl/core";
import type { Layer, LayerProps } from "@deck.gl/core";
import type { ColumnLayer } from "@deck.gl/layers";
import type { ModelKind, createObjectModels } from "./objectModels";
import type { GraphicsMode } from "../../utils/graphicsPreference";

/** Run `fn` after the map has had its first frames and the browser is idle — never in the critical path. */
function afterFirstFrame(fn: () => void) {
  const idle = () => {
    const ric = (window as unknown as { requestIdleCallback?: (cb: () => void, o?: { timeout: number }) => void }).requestIdleCallback;
    if (ric) ric(fn, { timeout: 2000 }); else setTimeout(fn, 200);
  };
  requestAnimationFrame(() => requestAnimationFrame(idle));
}

/**
 * Only this small boundary is in the normal entry; all model code stays lazy.
 *
 * ⛔ ALWAYS this one class, whatever the mode. deck.gl's LayerManager matches layers by id and
 * transfers the old layer's state into the new one, so a layer id that flips class between
 * ColumnLayer and a composite crashes ("getBufferLayouts" of null). The mode is a prop; the
 * public id stays the column's id, and the sublayer id ("columns" / "objects") is what changes.
 */
class LazyObjectModels extends CompositeLayer<{ column: ColumnLayer; kind: ModelKind; mode: GraphicsMode }> {
  static layerName = "LazyObjectModels";
  declare state: { create?: typeof createObjectModels; loading?: boolean };
  initializeState() { this.maybeLoad(); }
  updateState() { this.maybeLoad(); }
  /** Enhanced only, once per layer instance, deferred past the first frame. Simple mode never imports. */
  private maybeLoad() {
    if (this.props.mode !== "enhanced" || this.state.create || this.state.loading) return;
    this.setState({ loading: true });
    afterFirstFrame(() => {
      void import("./objectModels").then(module => {
        this.getCurrentLayer()?.setState({ create: module.createObjectModels });
      }).catch(error => {
        console.warn("[3d-models] falling back to columns:", error);
        this.getCurrentLayer()?.setState({ loading: false });
      });
    });
  }
  renderLayers(): Layer {
    const useModels = this.props.mode === "enhanced" && this.state.create;
    const props = this.getSubLayerProps({ id: useModels ? "objects" : "columns" });
    return useModels && this.state.create
      ? this.state.create(this.props.column, this.props.kind, props)
      : this.props.column.clone(props);
  }
}

/** Always the same composite class (see above); "simple" renders the column and never imports the model chunk. */
export function withObjectModels(column: ColumnLayer, kind: ModelKind, mode: GraphicsMode): Layer {
  const props: Partial<LayerProps> = {};
  for (const key of ["pickable", "visible", "autoHighlight", "highlightColor", "onClick",
    "coordinateSystem", "coordinateOrigin", "modelMatrix", "wrapLongitude"] as const) {
    Object.assign(props, { [key]: column.props[key] });
  }
  return new LazyObjectModels({ ...props, id: column.id, data: column.props.data, column, kind, mode });
}
