struct Uniforms {
  view_proj: mat4x4<f32>,
  cam_eye: vec4<f32>,       // xyz = eye, w = z_exag
  grid_info: vec4<f32>,     // x = dx, y = z_min, z = z_max, w = max_hag
  grid_dims: vec4<u32>,     // x = nx, y = ny, z = primary_layer, w = compare_layer
  wipe_sun: vec4<f32>,
  viewport: vec4<f32>,      // x = width_px, y = height_px, z = peel, w = point_size_m
  flags: vec4<f32>,
  flags2: vec4<f32>,
};

@group(0) @binding(0) var<uniform> u: Uniforms;
@group(0) @binding(1) var<storage, read> canopy_pts: array<vec4<f32>>;

struct VsOut {
  @builtin(position) clip_pos: vec4<f32>,
  @location(0) quad_uv: vec2<f32>,
  @location(1) color: vec3<f32>,
  @location(2) alpha: f32,
};

fn hash_u32(n: u32) -> f32 {
  var x = n;
  x = ((x >> 16u) ^ x) * 0x45d9f3bu;
  x = ((x >> 16u) ^ x) * 0x45d9f3bu;
  x = (x >> 16u) ^ x;
  return f32(x & 0x00ffffffu) / 16777215.0;
}

@vertex
fn vs_main(
  @builtin(vertex_index) vid: u32,
  @builtin(instance_index) iid: u32
) -> VsOut {
  var out: VsOut;

  let peel = clamp(u.viewport.z, 0.0, 1.0);
  if (peel <= 0.001) {
    out.clip_pos = vec4<f32>(0.0, 0.0, 2.0, 1.0);
    out.quad_uv = vec2<f32>(0.0);
    out.color = vec3<f32>(0.0);
    out.alpha = 0.0;
    return out;
  }

  let pt = canopy_pts[iid]; // rel_x, rel_y, z_abs, hag
  let hag = max(pt.w, 0.0);
  let hag_norm = clamp(hag / max(u.grid_info.w, 1.0), 0.0, 1.0);
  let h = hash_u32(iid + 1u);

  // Rank in [0.02, 0.999]; upper canopy and denser points strip away first as peel goes 1 -> 0
  let rank = clamp(0.02 + 0.56 * hag_norm + 0.419 * h, 0.02, 0.999);
  let margin = peel * 1.08 - rank;
  if (margin <= 0.0) {
    out.clip_pos = vec4<f32>(0.0, 0.0, 2.0, 1.0);
    out.quad_uv = vec2<f32>(0.0);
    out.color = vec3<f32>(0.0);
    out.alpha = 0.0;
    return out;
  }

  let dx = u.grid_info.x;
  let width_m = f32(u.grid_dims.x) * dx;
  let height_m = f32(u.grid_dims.y) * dx;
  let z_mid = 0.5 * (u.grid_info.y + u.grid_info.z);

  let wx = pt.x - width_m * 0.5;
  let wy = pt.y - height_m * 0.5;
  let wz = (pt.z - z_mid) * u.cam_eye.w;
  let center = vec3<f32>(wx, wy, wz);

  let to_cam = normalize(u.cam_eye.xyz - center);
  let ref_up = select(vec3<f32>(0.0, 0.0, 1.0), vec3<f32>(0.0, 1.0, 0.0), abs(to_cam.z) > 0.995);
  let right = normalize(cross(ref_up, to_cam));
  let up = cross(to_cam, right);

  var corners = array<vec2<f32>, 6>(
    vec2<f32>(-1.0, -1.0),
    vec2<f32>( 1.0, -1.0),
    vec2<f32>( 1.0,  1.0),
    vec2<f32>(-1.0, -1.0),
    vec2<f32>( 1.0,  1.0),
    vec2<f32>(-1.0,  1.0)
  );
  let corner = corners[vid];
  let scale = clamp(margin / 0.12, 0.0, 1.0);
  let radius = u.viewport.w * (0.65 + 0.55 * hag_norm) * scale;
  let world_pos = center + (right * corner.x + up * corner.y) * radius;

  // Forest canopy vertical gradient: olive understory -> emerald mid -> sunlit chartreuse crown
  let c_low = vec3<f32>(0.36, 0.48, 0.24);
  let c_mid = vec3<f32>(0.15, 0.49, 0.30);
  let c_top = vec3<f32>(0.54, 0.80, 0.34);
  var col = c_mid;
  if (hag_norm < 0.35) {
    col = mix(c_low, c_mid, hag_norm / 0.35);
  } else {
    col = mix(c_mid, c_top, (hag_norm - 0.35) / 0.65);
  }
  // Subtle micro-variation
  col *= 0.86 + 0.24 * h;

  out.clip_pos = u.view_proj * vec4<f32>(world_pos, 1.0);
  out.quad_uv = corner;
  out.color = col;
  out.alpha = scale;
  return out;
}

@fragment
fn fs_main(in: VsOut) -> @location(0) vec4<f32> {
  if (in.alpha <= 0.05) {
    discard;
  }
  let r2 = dot(in.quad_uv, in.quad_uv);
  if (r2 > 1.0) {
    discard;
  }
  // Subtle spherical shading on foliage splat
  let shade = 0.72 + 0.28 * (1.0 - r2);
  return vec4<f32>(in.color * shade, 1.0);
}
