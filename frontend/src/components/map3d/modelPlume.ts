// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { ScatterplotLayer } from "@deck.gl/layers";
import type { LayerContext } from "@deck.gl/core";
import type { ShaderModule } from "@luma.gl/shadertools";

const plume = {
  name: "atlasPlume",
  vs: `uniform atlasPlumeUniforms { float time; } atlasPlume;`,
  uniformTypes: { time: "f32" },
} as const satisfies ShaderModule<{ time: number }>;

/** Static instance buffers; only a time uniform changes while particles rise. */
export class ModelPlumeLayer<DataT> extends ScatterplotLayer<DataT> {
  static layerName = "ModelPlumeLayer";
  declare state: ScatterplotLayer<DataT>["state"] & { frame: number | null; last: number };
  initializeState() {
    super.initializeState();
    this.state.frame = null;
    this.state.last = 0;
    const tick = (time: number) => {
      const current = this.getCurrentLayer() as ModelPlumeLayer<DataT> | null;
      if (!current) return;
      if (time - current.state.last >= 1000 / 30) {
        current.state.last = time;
        current.setNeedsRedraw();
      }
      current.state.frame = requestAnimationFrame(tick);
    };
    this.state.frame = requestAnimationFrame(tick);
  }
  finalizeState(context: LayerContext) {
    if (this.state.frame !== null) cancelAnimationFrame(this.state.frame);
    super.finalizeState(context);
  }
  getShaders() {
    const shaders = super.getShaders();
    const vs = shaders.vs!.replace("void main(void) {", `void main(void) {
      float phase = fract(instanceLineWidths + atlasPlume.time * 0.14);
      vec3 plumePosition = instancePositions;
      plumePosition.z += phase * instanceRadius * 6.5;
      plumePosition.x += instanceRadius * phase * 0.65 * sin(phase * 5.0 + instanceLineWidths * 9.0)
        / (111320.0 * max(0.05, cos(radians(instancePositions.y))));
    `).replaceAll("project_position_to_clipspace(instancePositions,", "project_position_to_clipspace(plumePosition,")
      .replace("scatterplot.radiusScale * instanceRadius,", "scatterplot.radiusScale * instanceRadius * (0.20 + phase * 0.90),")
      .replace("instanceFillColors.a * layer.opacity", "instanceFillColors.a * layer.opacity * sin(phase * 3.14159265)");
    const fs = shaders.fs!.replace("fragColor.a *= inCircle;", "fragColor.a *= inCircle * pow(max(0.0, 1.0 - dot(unitPosition, unitPosition)), 0.65);");
    return { ...shaders, vs, fs, modules: [...shaders.modules, plume] };
  }
  draw(options: Parameters<ScatterplotLayer<DataT>["draw"]>[0]) {
    this.setShaderModuleProps({ atlasPlume: { time: performance.now() / 1000 } });
    super.draw(options);
  }
}
