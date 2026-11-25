struct Uniforms {
  view_proj: mat4x4<f32>,   // offset 0
  cam_eye: vec4<f32>,       // xyz = eye, w = z_exag
  grid_info: vec4<f32>,     // x = dx, y = z_min, z = z_max, w = max_hag
  grid_dims: vec4<u32>,     // x = nx, y = ny, z = primary_layer, w = compare_layer
  wipe_sun: vec4<f32>,      // x = split_enabled, y = split_x, z = sun_az_rad, w = sun_el_rad
  viewport: vec4<f32>,      // x = width_px, y = height_px, z = peel, w = point_size_m
  flags: vec4<f32>,         // x = show_grid, y = has_usa10, z = has_old10, w = has_gazo1
  flags2: vec4<f32>,        // x = has_seamless, y = dpr, z = 0.0, w = 0.0
};

@group(0) @binding(0) var<uniform> u: Uniforms;
@group(0) @binding(1) var<storage, read> grid_data: array<f32>;
@group(0) @binding(2) var aerial_sampler: sampler;
@group(0) @binding(3) var tex_usa10: texture_2d<f32>;
@group(0) @binding(4) var tex_old10: texture_2d<f32>;
@group(0) @binding(5) var tex_gazo1: texture_2d<f32>;
@group(0) @binding(6) var tex_seamless: texture_2d<f32>;

struct VsOut {
  @builtin(position) clip_pos: vec4<f32>,
  @location(0) uv: vec2<f32>,
  @location(1) grid_coord: vec2<f32>,
  @location(2) world_pos: vec3<f32>,
};

fn read_cell(layer_idx: u32, col: i32, row: i32) -> f32 {
  let nx = i32(u.grid_dims.x);
  let ny = i32(u.grid_dims.y);
  let c = clamp(col, 0, nx - 1);
  let r = clamp(row, 0, ny - 1);
  let stride = u32(nx * ny);
  return grid_data[layer_idx * stride + u32(r * nx + c)];
}

fn sample_bilinear(layer_idx: u32, gx: f32, gy: f32) -> f32 {
  let nx = f32(u.grid_dims.x);
  let ny = f32(u.grid_dims.y);
  let cx = clamp(gx, 0.0, nx - 1.001);
  let cy = clamp(gy, 0.0, ny - 1.001);
  let c0 = i32(floor(cx));
  let r0 = i32(floor(cy));
  let c1 = min(i32(u.grid_dims.x) - 1, c0 + 1);
  let r1 = min(i32(u.grid_dims.y) - 1, r0 + 1);
  let fx = cx - f32(c0);
  let fy = cy - f32(r0);

  let v00 = read_cell(layer_idx, c0, r0);
  let v10 = read_cell(layer_idx, c1, r0);
  let v01 = read_cell(layer_idx, c0, r1);
  let v11 = read_cell(layer_idx, c1, r1);
  return mix(mix(v00, v10, fx), mix(v01, v11, fx), fy);
}

fn compute_normal_metric(gx: f32, gy: f32) -> vec3<f32> {
  let dx = u.grid_info.x;
  let z_l = sample_bilinear(0u, gx - 1.0, gy);
  let z_r = sample_bilinear(0u, gx + 1.0, gy);
  let z_d = sample_bilinear(0u, gx, gy - 1.0);
  let z_u = sample_bilinear(0u, gx, gy + 1.0);
  let dzdx = (z_r - z_l) / (2.0 * dx);
  let dzdy = (z_u - z_d) / (2.0 * dx);
  return normalize(vec3<f32>(-dzdx, -dzdy, 1.0));
}

@vertex
fn vs_main(@builtin(vertex_index) vid: u32) -> VsOut {
  let nx = u.grid_dims.x;
  let ny = u.grid_dims.y;
  let col = vid % nx;
  let row = vid / nx;

  let dx = u.grid_info.x;
  let width_m = f32(nx) * dx;
  let height_m = f32(ny) * dx;

  let rel_x = (f32(col) + 0.5) * dx;
  let rel_y = (f32(row) + 0.5) * dx;

  let z = read_cell(0u, i32(col), i32(row));
  let z_mid = 0.5 * (u.grid_info.y + u.grid_info.z);

  let wx = rel_x - width_m * 0.5;
  let wy = rel_y - height_m * 0.5;
  let wz = (z - z_mid) * u.cam_eye.w;

  var out: VsOut;
  out.world_pos = vec3<f32>(wx, wy, wz);
  out.clip_pos = u.view_proj * vec4<f32>(wx, wy, wz, 1.0);
  // CONTRACT.md §2.3: u = rel_x / width_m, v = 1.0 - rel_y / height_m (v=0 is North)
  out.uv = vec2<f32>(rel_x / width_m, 1.0 - rel_y / height_m);
  out.grid_coord = vec2<f32>(f32(col), f32(row));
  return out;
}

fn color_svf(svf: f32) -> vec3<f32> {
  let t = clamp(svf, 0.0, 1.0);
  let c0 = vec3<f32>(0.04, 0.07, 0.14);
  let c1 = vec3<f32>(0.24, 0.34, 0.45);
  let c2 = vec3<f32>(0.93, 0.96, 0.99);
  if (t < 0.5) {
    return mix(c0, c1, t * 2.0);
  }
  return mix(c1, c2, (t - 0.5) * 2.0);
}

fn color_lrm(lrm: f32) -> vec3<f32> {
  // Diverging palette around 0m: [-2.0m .. 0 .. +2.0m]
  let t = clamp(lrm / 1.8, -1.0, 1.0);
  let neg = vec3<f32>(0.11, 0.42, 0.85);
  let mid = vec3<f32>(0.18, 0.21, 0.27);
  let pos = vec3<f32>(0.95, 0.46, 0.16);
  let pos_hi = vec3<f32>(1.0, 0.84, 0.42);
  if (t < 0.0) {
    return mix(mid, neg, -t);
  }
  if (t < 0.6) {
    return mix(mid, pos, t / 0.6);
  }
  return mix(pos, pos_hi, (t - 0.6) / 0.4);
}

fn color_flow_violation(v: f32) -> vec3<f32> {
  let t = clamp(v, 0.0, 1.0);
  let c0 = vec3<f32>(0.07, 0.09, 0.15);
  let c1 = vec3<f32>(0.48, 0.17, 0.72);
  let c2 = vec3<f32>(0.96, 0.49, 0.04);
  let c3 = vec3<f32>(1.0, 0.95, 0.65);
  if (t < 0.35) {
    return mix(c0, c1, t / 0.35);
  }
  if (t < 0.72) {
    return mix(c1, c2, (t - 0.35) / 0.37);
  }
  return mix(c2, c3, (t - 0.72) / 0.28);
}

fn color_rho_gnd(rho: f32, gx: f32, gy: f32) -> vec3<f32> {
  // Anti-hallucination provenance gate: red warning below 0.5 pts/m2
  if (rho < 0.5) {
    let stripe = step(0.5, fract((gx + gy) * 0.25));
    let severity = 1.0 - clamp(rho / 0.5, 0.0, 1.0);
    let red_lo = vec3<f32>(0.78, 0.10, 0.16);
    let red_hi = vec3<f32>(0.98, 0.22, 0.26);
    return mix(red_lo, red_hi, 0.45 * severity + 0.35 * stripe);
  }
  let t = clamp((rho - 0.5) / 3.5, 0.0, 1.0);
  let ok_lo = vec3<f32>(0.14, 0.58, 0.52);
  let ok_hi = vec3<f32>(0.68, 0.91, 0.76);
  return mix(ok_lo, ok_hi, t);
}

fn color_raking_sun(gx: f32, gy: f32, n: vec3<f32>) -> vec3<f32> {
  // sunAzimuthDeg is CW from North (+Y). So East = sin(az), North = cos(az).
  let az = u.wipe_sun.z;
  let el = u.wipe_sun.w;
  let cos_el = cos(el);
  let sun_dir = normalize(vec3<f32>(sin(az) * cos_el, cos(az) * cos_el, sin(el)));

  // Heightfield shadow ray march in grid cells
  let dx = u.grid_info.x;
  let z0 = sample_bilinear(0u, gx, gy);
  let horiz_step_cells = 1.5;
  let horiz_step_m = horiz_step_cells * dx;
  let step_xy = normalize(vec2<f32>(sin(az), cos(az))) * horiz_step_cells;
  let dz_per_step = tan(el) * horiz_step_m;

  var shadow = 1.0;
  var cur_xy = vec2<f32>(gx, gy);
  for (var i = 1; i <= 22; i++) {
    cur_xy += step_xy;
    if (cur_xy.x < 0.0 || cur_xy.y < 0.0 || cur_xy.x >= f32(u.grid_dims.x) || cur_xy.y >= f32(u.grid_dims.y)) {
      break;
    }
    let ray_z = z0 + dz_per_step * f32(i);
    let terrain_z = sample_bilinear(0u, cur_xy.x, cur_xy.y);
    if (terrain_z > ray_z + 0.04) {
      shadow = 0.22;
      break;
    }
  }

  let ndotl = max(dot(n, sun_dir), 0.0);
  let view_dir = normalize(u.cam_eye.xyz - vec3<f32>(0.0));
  let half_vec = normalize(sun_dir + view_dir);
  let spec = pow(max(dot(n, half_vec), 0.0), 28.0) * 0.24 * shadow;

  let svf = sample_bilinear(6u, gx, gy);
  let base_albedo = vec3<f32>(0.68, 0.69, 0.67);
  let ambient = 0.24 * (0.55 + 0.45 * svf) * vec3<f32>(0.66, 0.74, 0.85);
  let direct = 0.95 * ndotl * shadow * vec3<f32>(1.0, 0.94, 0.84);
  return clamp(base_albedo * (ambient + direct) + vec3<f32>(spec), vec3<f32>(0.0), vec3<f32>(1.0));
}

fn unavailable_pattern(uv: vec2<f32>) -> vec3<f32> {
  let check = step(0.5, fract(uv.x * 16.0)) * step(0.5, fract(uv.y * 16.0));
  return mix(vec3<f32>(0.14, 0.16, 0.20), vec3<f32>(0.24, 0.14, 0.16), check);
}

fn eval_layer(
  layer_id: u32,
  gx: f32,
  gy: f32,
  uv: vec2<f32>,
  n: vec3<f32>,
  c_usa10: vec3<f32>,
  c_old10: vec3<f32>,
  c_gazo1: vec3<f32>,
  c_seaml: vec3<f32>
) -> vec3<f32> {
  let subtle_shade = 0.85 + 0.15 * max(n.z, 0.0);
  switch (layer_id) {
    case 0u: { // Chiba RRIM
      let r = sample_bilinear(3u, gx, gy);
      let g = sample_bilinear(4u, gx, gy);
      let b = sample_bilinear(5u, gx, gy);
      return vec3<f32>(r, g, b);
    }
    case 1u: { // Live Raking-Light Sun
      return color_raking_sun(gx, gy, n);
    }
    case 2u: { // Zaksek SVF
      return color_svf(sample_bilinear(6u, gx, gy));
    }
    case 3u: { // Hesse LRM
      return color_lrm(sample_bilinear(7u, gx, gy));
    }
    case 4u: { // Drainage Violation
      return color_flow_violation(sample_bilinear(9u, gx, gy));
    }
    case 5u: { // Ground Confidence rho_gnd
      return color_rho_gnd(sample_bilinear(2u, gx, gy), gx, gy);
    }
    case 6u: { // GSI 1945 ort_USA10
      if (u.flags.y < 0.5) { return unavailable_pattern(uv); }
      return c_usa10 * subtle_shade;
    }
    case 7u: { // GSI 1965 ort_old10
      if (u.flags.z < 0.5) { return unavailable_pattern(uv); }
      return c_old10 * subtle_shade;
    }
    case 8u: { // GSI 1975 gazo1
      if (u.flags.w < 0.5) { return unavailable_pattern(uv); }
      return c_gazo1 * subtle_shade;
    }
    case 10u: {
      // Categorical nearest-cell lookup preserves blackout boundaries.
      let code = i32(read_cell(10u, i32(round(gx)), i32(round(gy))));
      switch code {
        case 0: { return vec3<f32>(141.,39.,69.)/255.; }
        case 1: { return vec3<f32>(85.,88.,103.)/255.; }
        case 2: { return vec3<f32>(231.,173.,103.)/255.; }
        case 3: { return vec3<f32>(169.,211.,191.)/255.; }
        case 4: { return vec3<f32>(86.,166.,158.)/255.; }
        case 5: { return vec3<f32>(34.,100.,113.)/255.; }
        default: { return unavailable_pattern(uv); }
      }
    }
    default: { // GSI Today seamlessphoto (9u)
      if (u.flags2.x < 0.5) { return unavailable_pattern(uv); }
      return c_seaml * subtle_shade;
    }
  }
}

@fragment
fn fs_main(in: VsOut) -> @location(0) vec4<f32> {
  // Sample all aerial textures in uniform control flow
  let c_usa10 = textureSample(tex_usa10, aerial_sampler, in.uv).rgb;
  let c_old10 = textureSample(tex_old10, aerial_sampler, in.uv).rgb;
  let c_gazo1 = textureSample(tex_gazo1, aerial_sampler, in.uv).rgb;
  let c_seaml = textureSample(tex_seamless, aerial_sampler, in.uv).rgb;

  let gx = in.grid_coord.x;
  let gy = in.grid_coord.y;
  let n = compute_normal_metric(gx, gy);

  var col = eval_layer(u.grid_dims.z, gx, gy, in.uv, n, c_usa10, c_old10, c_gazo1, c_seaml);

  if (u.wipe_sun.x > 0.5) {
    let screen_norm_x = in.clip_pos.x / max(u.viewport.x, 1.0);
    if (screen_norm_x > u.wipe_sun.y) {
      col = eval_layer(u.grid_dims.w, gx, gy, in.uv, n, c_usa10, c_old10, c_gazo1, c_seaml);
    }
    let dist_px = abs(screen_norm_x - u.wipe_sun.y) * u.viewport.x;
    if (dist_px < 1.5 * u.flags2.y) {
      col = vec3<f32>(0.98, 0.85, 0.32);
    }
  }

  // Optional 10m metric grid overlay
  if (u.flags.x > 0.5) {
    let dx = u.grid_info.x;
    let mx = fract((gx * dx) / 10.0);
    let my = fract((gy * dx) / 10.0);
    if (mx < 0.025 || my < 0.025) {
      col = mix(col, vec3<f32>(0.55, 0.78, 0.95), 0.25);
    }
  }

  return vec4<f32>(col, 1.0);
}
