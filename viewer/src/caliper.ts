import type { Vec3 } from './math';
import type { CaliperResult, CaliperSample, PlmpPack } from './types';

export function sampleLayerBilinear(
  layer: Float32Array,
  nx: number,
  ny: number,
  dx: number,
  relX: number,
  relY: number
): number {
  const gx = Math.max(0, Math.min(nx - 1.001, relX / dx - 0.5));
  const gy = Math.max(0, Math.min(ny - 1.001, relY / dx - 0.5));
  const c0 = Math.floor(gx);
  const r0 = Math.floor(gy);
  const c1 = Math.min(nx - 1, c0 + 1);
  const r1 = Math.min(ny - 1, r0 + 1);
  const fx = gx - c0;
  const fy = gy - r0;

  const v00 = layer[r0 * nx + c0];
  const v10 = layer[r0 * nx + c1];
  const v01 = layer[r1 * nx + c0];
  const v11 = layer[r1 * nx + c1];

  const a = v00 * (1 - fx) + v10 * fx;
  const b = v01 * (1 - fx) + v11 * fx;
  return a * (1 - fy) + b * fy;
}

/**
 * Raycast a world-space ray against the z_gnd heightfield.
 * World coordinates: wx = relX - widthM/2, wy = relY - heightM/2, wz = (z_gnd - zMid) * zExag
 */
export function raycastTerrain(
  pack: PlmpPack,
  zExag: number,
  origin: Vec3,
  dir: Vec3
): { relX: number; relY: number; zGnd: number } | null {
  const { nx, ny, dx, z_min, z_max } = pack.header;
  const widthM = nx * dx;
  const heightM = ny * dx;
  const halfW = widthM * 0.5;
  const halfH = heightM * 0.5;
  const zMid = 0.5 * (z_min + z_max);
  const zGndLayer = pack.layers.z_gnd;

  // Intersect ray with expanded bounding box
  const bMin: Vec3 = [-halfW, -halfH, (z_min - zMid) * zExag - 2.0];
  const bMax: Vec3 = [halfW, halfH, (z_max - zMid) * zExag + 2.0];

  let tMin = 0.5;
  let tMax = 2000.0;
  for (let axis = 0; axis < 3; axis++) {
    const o = origin[axis];
    const d = dir[axis];
    if (Math.abs(d) < 1e-8) {
      if (o < bMin[axis] || o > bMax[axis]) return null;
    } else {
      let t1 = (bMin[axis] - o) / d;
      let t2 = (bMax[axis] - o) / d;
      if (t1 > t2) {
        const tmp = t1;
        t1 = t2;
        t2 = tmp;
      }
      tMin = Math.max(tMin, t1);
      tMax = Math.min(tMax, t2);
      if (tMin > tMax) return null;
    }
  }

  const evalSignedDist = (t: number): { diff: number; relX: number; relY: number; zGnd: number } => {
    const wx = origin[0] + dir[0] * t;
    const wy = origin[1] + dir[1] * t;
    const wz = origin[2] + dir[2] * t;
    const relX = Math.max(0, Math.min(widthM, wx + halfW));
    const relY = Math.max(0, Math.min(heightM, wy + halfH));
    const zGnd = sampleLayerBilinear(zGndLayer, nx, ny, dx, relX, relY);
    const terrainWz = (zGnd - zMid) * zExag;
    return { diff: wz - terrainWz, relX, relY, zGnd };
  };

  const step = 0.5;
  let prevT = tMin;
  let prevEval = evalSignedDist(prevT);
  if (prevEval.diff <= 0) {
    return { relX: prevEval.relX, relY: prevEval.relY, zGnd: prevEval.zGnd };
  }

  for (let t = tMin + step; t <= tMax; t += step) {
    const cur = evalSignedDist(t);
    if (cur.diff <= 0) {
      // Binary refine between prevT and t
      let lo = prevT;
      let hi = t;
      for (let it = 0; it < 12; it++) {
        const mid = 0.5 * (lo + hi);
        const mEval = evalSignedDist(mid);
        if (mEval.diff > 0) {
          lo = mid;
        } else {
          hi = mid;
        }
      }
      const hit = evalSignedDist(0.5 * (lo + hi));
      return { relX: hit.relX, relY: hit.relY, zGnd: hit.zGnd };
    }
    prevT = t;
    prevEval = cur;
  }
  return null;
}

export function computeCaliperProfile(
  pack: PlmpPack,
  p0: { relX: number; relY: number; zGnd: number },
  p1: { relX: number; relY: number; zGnd: number },
  nSamples = 180
): CaliperResult {
  const { nx, ny, dx } = pack.header;
  const { z_gnd, rho_gnd, lrm } = pack.layers;

  const dX = p1.relX - p0.relX;
  const dY = p1.relY - p0.relY;
  const lengthM = Math.hypot(dX, dY);

  const samples: CaliperSample[] = [];
  let zMin = Infinity;
  let zMax = -Infinity;
  let lrmMin = Infinity;
  let lrmMax = -Infinity;
  let rhoMin = Infinity;
  let rhoSum = 0;

  const count = Math.max(2, nSamples);
  for (let i = 0; i < count; i++) {
    const t = i / (count - 1);
    const relX = p0.relX + dX * t;
    const relY = p0.relY + dY * t;
    const s = lengthM * t;

    const zG = sampleLayerBilinear(z_gnd, nx, ny, dx, relX, relY);
    const rho = sampleLayerBilinear(rho_gnd, nx, ny, dx, relX, relY);
    const lrmVal = sampleLayerBilinear(lrm, nx, ny, dx, relX, relY);

    samples.push({ s, relX, relY, zGnd: zG, rhoGnd: rho, lrm: lrmVal });

    if (zG < zMin) zMin = zG;
    if (zG > zMax) zMax = zG;
    if (lrmVal < lrmMin) lrmMin = lrmVal;
    if (lrmVal > lrmMax) lrmMax = lrmVal;
    if (rho < rhoMin) rhoMin = rho;
    rhoSum += rho;
  }

  // Compute max local scarp slope (deg) across ~1m windows to suppress sub-grid discretization noise
  let maxSlopeDeg = 0;
  const ds = lengthM / Math.max(1, count - 1);
  const stride = Math.max(1, Math.round(1.0 / Math.max(ds, 0.05)));
  if (lengthM > 0.1) {
    for (let i = stride; i < samples.length; i++) {
      const a = samples[i - stride];
      const b = samples[i];
      const horiz = Math.max(1e-4, b.s - a.s);
      const slopeDeg = (Math.atan(Math.abs(b.zGnd - a.zGnd) / horiz) * 180) / Math.PI;
      if (slopeDeg > maxSlopeDeg) maxSlopeDeg = slopeDeg;
    }
  }

  return {
    p0,
    p1,
    lengthM,
    samples,
    wallHeightM: Math.max(0, zMax - zMin),
    scarpSlopeDeg: maxSlopeDeg,
    localReliefM: Math.max(0, lrmMax - lrmMin),
    lrmMinM: lrmMin,
    lrmMaxM: lrmMax,
    minRhoGnd: rhoMin,
    meanRhoGnd: rhoSum / samples.length,
  };
}

export function drawCaliperProfileCanvas(
  canvas: HTMLCanvasElement,
  result: CaliperResult | null
): void {
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const cssW = canvas.clientWidth || 260;
  const cssH = canvas.clientHeight || 132;
  const w = Math.round(cssW * dpr);
  const h = Math.round(cssH * dpr);
  if (canvas.width !== w || canvas.height !== h) {
    canvas.width = w;
    canvas.height = h;
  }

  const ctx = canvas.getContext('2d');
  if (!ctx) return;
  ctx.save();
  ctx.scale(dpr, dpr);

  // Dark background
  ctx.fillStyle = '#0c1017';
  ctx.fillRect(0, 0, cssW, cssH);

  if (!result || result.samples.length < 2 || result.lengthM < 0.2) {
    ctx.strokeStyle = '#1f2937';
    ctx.strokeRect(0.5, 0.5, cssW - 1, cssH - 1);
    ctx.fillStyle = '#7f8ea3';
    ctx.font = '10px ui-monospace, SFMono-Regular, Menlo, monospace';
    ctx.textAlign = 'center';
    ctx.fillText('Caliper or Shift+Drag on terrain', cssW * 0.5, cssH * 0.5 - 4);
    ctx.fillStyle = '#536278';
    ctx.fillText('to slice z_gnd + rho_gnd', cssW * 0.5, cssH * 0.5 + 12);
    ctx.restore();
    return;
  }

  const padL = 32;
  const padR = 30;
  const padT = 14;
  const padB = 20;
  const plotW = Math.max(10, cssW - padL - padR);
  const plotH = Math.max(10, cssH - padT - padB);

  const samples = result.samples;
  let zMin = Infinity;
  let zMax = -Infinity;
  let rhoMax = 1.0;
  for (const s of samples) {
    if (s.zGnd < zMin) zMin = s.zGnd;
    if (s.zGnd > zMax) zMax = s.zGnd;
    if (s.rhoGnd > rhoMax) rhoMax = s.rhoGnd;
  }
  const zSpan = Math.max(0.5, zMax - zMin);
  zMin -= zSpan * 0.08;
  zMax += zSpan * 0.08;
  rhoMax = Math.max(2.0, Math.ceil(rhoMax * 1.15));

  const xOf = (s: number) => padL + (s / result.lengthM) * plotW;
  const yZ = (z: number) => padT + plotH - ((z - zMin) / (zMax - zMin)) * plotH;
  const yRho = (r: number) => padT + plotH - (Math.min(r, rhoMax) / rhoMax) * plotH;

  // Grid lines
  ctx.strokeStyle = '#1c2533';
  ctx.lineWidth = 1;
  for (let i = 0; i <= 3; i++) {
    const yy = padT + (plotH * i) / 3;
    ctx.beginPath();
    ctx.moveTo(padL, yy);
    ctx.lineTo(padL + plotW, yy);
    ctx.stroke();
  }

  // Shade low-rho_gnd (< 0.5 pts/m2) spans in translucent red
  ctx.fillStyle = 'rgba(230, 57, 70, 0.22)';
  for (let i = 0; i < samples.length - 1; i++) {
    if (samples[i].rhoGnd < 0.5 || samples[i + 1].rhoGnd < 0.5) {
      const x0 = xOf(samples[i].s);
      const x1 = xOf(samples[i + 1].s);
      ctx.fillRect(x0, padT, Math.max(1, x1 - x0), plotH);
    }
  }

  // 0.5 pts/m2 warning threshold horizontal dashed line
  const yThresh = yRho(0.5);
  ctx.save();
  ctx.strokeStyle = '#ff4d5a';
  ctx.setLineDash([4, 3]);
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(padL, yThresh);
  ctx.lineTo(padL + plotW, yThresh);
  ctx.stroke();
  ctx.restore();

  // Elevation filled polygon
  ctx.beginPath();
  ctx.moveTo(xOf(samples[0].s), padT + plotH);
  for (const s of samples) {
    ctx.lineTo(xOf(s.s), yZ(s.zGnd));
  }
  ctx.lineTo(xOf(samples[samples.length - 1].s), padT + plotH);
  ctx.closePath();
  const grad = ctx.createLinearGradient(0, padT, 0, padT + plotH);
  grad.addColorStop(0, 'rgba(56, 189, 248, 0.34)');
  grad.addColorStop(1, 'rgba(56, 189, 248, 0.03)');
  ctx.fillStyle = grad;
  ctx.fill();

  // Elevation line
  ctx.strokeStyle = '#38bdf8';
  ctx.lineWidth = 1.8;
  ctx.beginPath();
  samples.forEach((s, idx) => {
    const x = xOf(s.s);
    const y = yZ(s.zGnd);
    if (idx === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();

  // rho_gnd line (emerald when >=0.5, red where <0.5)
  ctx.lineWidth = 1.4;
  for (let i = 0; i < samples.length - 1; i++) {
    const a = samples[i];
    const b = samples[i + 1];
    ctx.strokeStyle = a.rhoGnd < 0.5 || b.rhoGnd < 0.5 ? '#ff4d5a' : '#34d399';
    ctx.beginPath();
    ctx.moveTo(xOf(a.s), yRho(a.rhoGnd));
    ctx.lineTo(xOf(b.s), yRho(b.rhoGnd));
    ctx.stroke();
  }

  // Axis labels
  ctx.fillStyle = '#93c5fd';
  ctx.font = '10px ui-monospace, SFMono-Regular, Menlo, monospace';
  ctx.textAlign = 'right';
  ctx.fillText(zMax.toFixed(1), padL - 3, padT + 7);
  ctx.fillText(zMin.toFixed(1), padL - 3, padT + plotH);

  ctx.fillStyle = '#6ee7b7';
  ctx.textAlign = 'left';
  ctx.fillText(`${rhoMax.toFixed(0)}/m²`, padL + plotW + 3, padT + 7);
  ctx.fillStyle = '#ff6b78';
  ctx.fillText('0.5', padL + plotW + 3, Math.min(padT + plotH, Math.max(padT + 14, yThresh + 3)));

  ctx.fillStyle = '#94a3b8';
  ctx.textAlign = 'center';
  ctx.fillText(`0m`, padL, cssH - 5);
  ctx.fillText(`${result.lengthM.toFixed(1)}m`, padL + plotW - 10, cssH - 5);
  ctx.fillStyle = '#cbd5e1';
  ctx.fillText(`z_gnd (m) & rho_gnd (/m²)`, padL + plotW * 0.5, 10);

  ctx.restore();
}
