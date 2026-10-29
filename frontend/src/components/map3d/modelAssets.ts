// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { SimpleMeshLayer } from "@deck.gl/mesh-layers";
import { load } from "@loaders.gl/core";
import { GLTFLoader, postProcessGLTF } from "@loaders.gl/gltf";
import type { GLTFWithBuffers } from "@loaders.gl/gltf";
import type { ShaderModule } from "@luma.gl/shadertools";
import type { ModelKind } from "./objectModels";
import { overviewWeight } from "./modelOverview";

const style = {
  name: "atlasModel",
  fs: `uniform atlasModelUniforms { float hot; float overview; } atlasModel;`,
  uniformTypes: { hot: "f32", overview: "f32" },
} as const satisfies ShaderModule<{ hot: number; overview: number }>;

/** One draw per variant; tint, texture, relief and picking share the same shader. */
class AtlasMeshLayer<DataT = unknown> extends SimpleMeshLayer<DataT, { hot: boolean }> {
  static layerName = "AtlasMeshLayer";
  getShaders() {
    const shaders = super.getShaders();
    return { ...shaders, modules: [...shaders.modules, style], fs: `#version 300 es
      precision highp float;
      uniform sampler2D sampler;
      in vec2 vTexCoord;
      in vec3 normals_commonspace;
      in vec4 vColor;
      out vec4 fragColor;
      void main() {
        geometry.uv = vTexCoord;
        vec3 grain = texture(sampler, vTexCoord).rgb;
        vec3 normal = normalize(normals_commonspace);
        float diffuse = max(dot(normal, normalize(vec3(-0.45, -0.55, 0.85))), 0.0);
        float light = max(0.40 + 0.60 * diffuse, mix(0.38, 0.54, atlasModel.overview));
        light = max(light, atlasModel.hot * 0.92);
        vec3 color = vColor.rgb * (0.72 + 0.28 * grain) * light;
        color += atlasModel.hot * vec3(0.12, 0.025, 0.0);
        fragColor = vec4(color, vColor.a * layer.opacity);
        DECKGL_FILTER_COLOR(fragColor, geometry);
      }` };
  }
  draw(options: Parameters<SimpleMeshLayer<DataT>["draw"]>[0]) {
    this.setShaderModuleProps({ atlasModel: { hot: this.props.hot ? 1 : 0,
      overview: overviewWeight(this.context.viewport.zoom) } });
    super.draw(options);
  }
}

type Attribute = { value: Float32Array; size: number };
type Mesh = { attributes: { POSITION: Attribute; NORMAL: Attribute; TEXCOORD_0: Attribute; COLOR_0: Attribute };
  indices: { value: Uint32Array; size: number } };
export type ModelAssets = { MeshLayer: typeof AtlasMeshLayer; meshes: Mesh[]; texture: string };

/** Merge GLB primitives once, preserving normals, UVs and mineral material colors. */
function meshFromGLTF(scene: GLTFWithBuffers): Mesh {
  const primitives = postProcessGLTF(scene).meshes[0].primitives;
  const count = primitives.reduce((sum, p) => sum + p.attributes.POSITION.value.length / 3, 0);
  const positions = new Float32Array(count * 3);
  const normals = new Float32Array(count * 3);
  const uv = new Float32Array(count * 2);
  const colors = new Float32Array(count * 3);
  const indices = new Uint32Array(primitives.reduce((sum, p) => sum + p.indices!.value.length, 0));
  let vertexOffset = 0, indexOffset = 0;
  for (const primitive of primitives) {
    const attributes = primitive.attributes;
    positions.set(attributes.POSITION.value, vertexOffset * 3);
    normals.set(attributes.NORMAL.value, vertexOffset * 3);
    uv.set(attributes.TEXCOORD_0.value, vertexOffset * 2);
    const tint = primitive.material?.pbrMetallicRoughness?.baseColorFactor || [1, 1, 1, 1];
    const vertices = attributes.POSITION.value.length / 3;
    for (let i = 0; i < vertices; i++) colors.set(tint.slice(0, 3), (vertexOffset + i) * 3);
    for (const index of primitive.indices!.value) indices[indexOffset++] = index + vertexOffset;
    vertexOffset += vertices;
  }
  return { attributes: {
    POSITION: { value: positions, size: 3 }, NORMAL: { value: normals, size: 3 },
    TEXCOORD_0: { value: uv, size: 2 }, COLOR_0: { value: colors, size: 3 },
  }, indices: { value: indices, size: 1 } };
}

const cache = new Map<ModelKind, Promise<ModelAssets>>();
export function loadModelAssets(kind: ModelKind): Promise<ModelAssets> {
  let pending = cache.get(kind);
  if (!pending) {
    const names = kind === "seamount" ? [0, 1, 2, 3].map(i => `seamount-${i}`) : [`vent-${kind}`];
    pending = Promise.all(names.map(name => load(`${import.meta.env.BASE_URL}models/${name}.glb`, GLTFLoader,
      { gltf: { loadImages: false } }))).then(scenes => ({ MeshLayer: AtlasMeshLayer,
      meshes: scenes.map(meshFromGLTF), texture: `${import.meta.env.BASE_URL}textures/${kind === "seamount" ? "basalt-manganese" : "chimney-minerals"}.jpg` }));
    cache.set(kind, pending);
  }
  return pending;
}
