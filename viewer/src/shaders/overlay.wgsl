struct Uniforms {
  view_proj: mat4x4<f32>,
};

@group(0) @binding(0) var<uniform> u: Uniforms;

struct VsOut {
  @builtin(position) clip_pos: vec4<f32>,
  @location(0) kind: f32,
};

@vertex
fn vs_main(@location(0) pos_kind: vec4<f32>) -> VsOut {
  var out: VsOut;
  out.clip_pos = u.view_proj * vec4<f32>(pos_kind.xyz, 1.0);
  out.kind = pos_kind.w;
  return out;
}

@fragment
fn fs_main(in: VsOut) -> @location(0) vec4<f32> {
  if (in.kind > 0.5) {
    // Endpoint beacon (amber)
    return vec4<f32>(1.0, 0.76, 0.16, 1.0);
  }
  // Transect ribbon (bright cyan)
  return vec4<f32>(0.15, 0.92, 0.98, 1.0);
}
