"""Tier 2 Roering et al. (1999) Nonlinear Soil-Creep Benchmark for PALIMPSEST.

Implements:
1. Conservative 2D finite-volume PDE solver for Roering et al. (1999)
   nonlinear slope-dependent hillslope sediment transport:
       dz/dt = -div(q_s),  q_s = -K * grad(z) / (1 - (|grad(z)| / Sc)^2)
   with Sc = 1.25 and slope-stability clamping |grad(z)| <= 0.98 * Sc.
2. Direct injection onto real raw forest LiDAR ground returns from
   `data/cache/lidar/*.laz` (Takatenjin West Ridge) across varying local
   rho_gnd strata ([0.5, 1.0), [1.0, 2.5), [2.5, 5.0), >= 5.0 pts/m^2):
   - 45 Roering-weathered synthetic ruins:
     * 15 terraced pads/retaining walls (`terrace`)
     * 15 circular mounds/kiln pits (`mound_pit`)
     * 15 ridge-cutting incisions (`horikiri`)
     across t in {100, 300, 800} yr (5 per morphology per age).
   - 20 natural decoys (7 rotational slumps, 7 tree-throw pit-mounds, 6 fluvial gullies).
3. End-to-end evaluation via `palimpsest` (CSF, DTM/CHM/rho_gnd, derivatives,
   detector + BH-FDR q <= 0.05) reporting empirical FDR, Precision, Recall
   by morphology class, Recall by weathering age, and Recall by rho_gnd bin.
"""

from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Any

import laspy
import numpy as np
import psutil
from scipy.ndimage import gaussian_filter
from scipy.spatial import cKDTree
from scipy.interpolate import LinearNDInterpolator


# Real forested Takatenjin tiles spanning ridge crests, steep slopes, and all rho_gnd strata
DEFAULT_BENCHMARK_TILES = [
    "08OC7888.laz",
    "08OC7889.laz",
    "08OC7898.laz",
    "08OC8828.laz",
]


def evolve_roering_1999(
    z0: np.ndarray,
    dx: float,
    t_years: float,
    K: float = 0.004,
    Sc: float = 1.25,
    clamp_frac: float = 0.98,
) -> np.ndarray:
    """Conservative staggered-face finite-volume solver for Roering et al. (1999) soil creep.

    dz/dt = -div(q_s), q_s = -K * grad(z) / (1 - (|grad(z)| / Sc)^2).
    Neumann zero-flux boundary conditions preserve total volume exactly.
    """
    z = np.asarray(z0, dtype=np.float64).copy()
    if t_years <= 0.0:
        return z

    s_max = clamp_frac * Sc
    sc2 = Sc * Sc
    inv_dx = 1.0 / dx
    inv_4dx = 0.25 / dx
    t_rem = float(t_years)

    while t_rem > 1e-12:
        # East faces: shape (ny, nx - 1)
        dz_dx_e = (z[:, 1:] - z[:, :-1]) * inv_dx
        z_pad_y = np.pad(z, ((1, 1), (0, 0)), mode="edge")
        dz_dy_e = (
            (z_pad_y[2:, :-1] - z_pad_y[:-2, :-1])
            + (z_pad_y[2:, 1:] - z_pad_y[:-2, 1:])
        ) * inv_4dx
        grad2_e = np.minimum(dz_dx_e * dz_dx_e + dz_dy_e * dz_dy_e, s_max * s_max)
        D_e = K / (1.0 - grad2_e / sc2)
        qx = -D_e * dz_dx_e

        # North faces: shape (ny - 1, nx)
        dz_dy_n = (z[1:, :] - z[:-1, :]) * inv_dx
        z_pad_x = np.pad(z, ((0, 0), (1, 1)), mode="edge")
        dz_dx_n = (
            (z_pad_x[:-1, 2:] - z_pad_x[:-1, :-2])
            + (z_pad_x[1:, 2:] - z_pad_x[1:, :-2])
        ) * inv_4dx
        grad2_n = np.minimum(dz_dx_n * dz_dx_n + dz_dy_n * dz_dy_n, s_max * s_max)
        D_n = K / (1.0 - grad2_n / sc2)
        qy = -D_n * dz_dy_n

        D_max = max(float(D_e.max()), float(D_n.max()), 1e-12)
        dt = min(t_rem, 0.20 * dx * dx / D_max)
        c = dt * inv_dx

        z[:, :-1] -= c * qx
        z[:, 1:] += c * qx
        z[:-1, :] -= c * qy
        z[1:, :] += c * qy
        t_rem -= dt

    return z


def _run_csf_mask(xyz: np.ndarray, use_palimpsest: bool = True) -> np.ndarray:
    """Classify ground points using palimpsest.lidar.run_csf_tile (or CSF directly in --self-test)."""
    if use_palimpsest:
        try:
            from palimpsest.lidar import run_csf_tile

            return run_csf_tile(
                xyz,
                cloth_resolution=0.75,
                rigidness=2,
                class_threshold=0.30,
                b_sloop_smooth=True,
                iterations=500,
            )
        except ImportError:
            pass

    import CSF

    csf = CSF.CSF()
    csf.params.bSloopSmooth = True
    csf.params.cloth_resolution = 0.75
    csf.params.rigidness = 2
    csf.params.time_step = 0.65
    csf.params.class_threshold = 0.30
    csf.params.interations = 500
    csf.setPointCloud(np.ascontiguousarray(xyz, dtype=np.float64))
    ground = CSF.VecInt()
    non_ground = CSF.VecInt()
    csf.do_filtering(ground, non_ground)
    mask = np.zeros(len(xyz), dtype=bool)
    mask[np.asarray(list(ground), dtype=np.int64)] = True
    return mask


def _grid_tile_from_points(
    x: np.ndarray,
    y: np.ndarray,
    z: np.ndarray,
    gmask: np.ndarray,
    x0: float,
    y0: float,
    width_m: float,
    height_m: float,
    dx: float = 0.5,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Grid bare-earth DTM, CHM, and local rho_gnd (pts/m^2) on (ny, nx) grid."""
    nx = int(round(width_m / dx))
    ny = int(round(height_m / dx))

    gx, gy, gz = x[gmask], y[gmask], z[gmask]

    # Ground cell aggregation
    col_g = np.floor((gx - x0) / dx).astype(np.int64)
    row_g = np.floor((gy - y0) / dx).astype(np.int64)
    in_g = (col_g >= 0) & (col_g < nx) & (row_g >= 0) & (row_g < ny)
    col_g, row_g, gz_in = col_g[in_g], row_g[in_g], gz[in_g]

    flat_g = row_g * nx + col_g
    g_sum = np.bincount(flat_g, weights=gz_in, minlength=nx * ny).reshape(ny, nx)
    g_cnt = np.bincount(flat_g, minlength=nx * ny).reshape(ny, nx)

    has_g = g_cnt > 0
    dtm = np.empty((ny, nx), dtype=np.float64)
    dtm[has_g] = g_sum[has_g] / g_cnt[has_g]

    if not np.all(has_g):
        xs_c = x0 + (np.arange(nx, dtype=np.float64) + 0.5) * dx
        ys_c = y0 + (np.arange(ny, dtype=np.float64) + 0.5) * dx
        Xc, Yc = np.meshgrid(xs_c, ys_c, indexing="xy")
        interp = LinearNDInterpolator(np.column_stack([Xc[has_g], Yc[has_g]]), dtm[has_g])
        miss = ~has_g
        filled = interp(Xc[miss], Yc[miss])
        nan_mask = ~np.isfinite(filled)
        if np.any(nan_mask):
            tree = cKDTree(np.column_stack([Xc[has_g], Yc[has_g]]))
            _, nn = tree.query(np.column_stack([Xc[miss][nan_mask], Yc[miss][nan_mask]]))
            filled[nan_mask] = dtm[has_g][nn]
        dtm[miss] = filled

    # Smoothed local rho_gnd (pts/m^2) over 2m radius Gaussian / box equivalent
    raw_rho = g_cnt.astype(np.float64) / (dx * dx)
    rho_gnd = gaussian_filter(raw_rho, sigma=2.0, mode="nearest")

    # DSM (max return per cell) & CHM
    col_a = np.floor((x - x0) / dx).astype(np.int64)
    row_a = np.floor((y - y0) / dx).astype(np.int64)
    in_a = (col_a >= 0) & (col_a < nx) & (row_a >= 0) & (row_a < ny)
    flat_a = row_a[in_a] * nx + col_a[in_a]
    dsm_flat = np.full(nx * ny, -np.inf, dtype=np.float64)
    np.maximum.at(dsm_flat, flat_a, z[in_a])
    dsm = dsm_flat.reshape(ny, nx)
    dsm = np.where(np.isfinite(dsm), dsm, dtm)
    chm = np.maximum(0.0, dsm - dtm)

    return dtm.astype(np.float32), chm.astype(np.float32), rho_gnd.astype(np.float32)


# ---------------------------------------------------------------------------
# Synthetic Ruin & Natural Decoy Heightfield Generators (pre-Roering)
# ---------------------------------------------------------------------------

def _make_terrace_target(z_bg: np.ndarray, Xl: np.ndarray, Yl: np.ndarray, radius_m: float = 8.5) -> np.ndarray:
    """Create flat terrace tread (|grad z| < 3 deg) with crisp >35 deg cut/fill riser."""
    r = np.hypot(Xl, Yl)
    z_center = float(z_bg[z_bg.shape[0] // 2, z_bg.shape[1] // 2])
    # Slight 1.5 deg natural drainage tilt across pad
    z_pad = z_center + 0.02 * Xl
    scarp_w = 2.0
    t = np.clip((r - radius_m) / scarp_w, 0.0, 1.0)
    w = 0.5 * (1.0 - np.cos(math.pi * t))  # smooth C1 ramp from 0 (inside) to 1 (outside)
    return (1.0 - w) * z_pad + w * z_bg


def _make_mound_pit_target(z_bg: np.ndarray, Xl: np.ndarray, Yl: np.ndarray, r_rim: float = 5.5) -> np.ndarray:
    """Create circular kiln pit / mound with closed annular rim."""
    r = np.hypot(Xl, Yl)
    pit_depth = -1.45 * np.exp(-(r / (0.55 * r_rim)) ** 4)
    rim = 0.90 * np.exp(-((r - r_rim) / 1.45) ** 2)
    outer_taper = np.clip(1.0 - np.maximum(0.0, r - (r_rim + 3.0)) / 4.0, 0.0, 1.0)
    return z_bg + (pit_depth + rim) * outer_taper


def _make_horikiri_target(
    z_bg: np.ndarray,
    Xl: np.ndarray,
    Yl: np.ndarray,
    ridge_angle_rad: float,
) -> np.ndarray:
    """Create ridge-cutting incision (horikiri) oriented 90 deg transverse to ridge axis."""
    # Coordinates (u along ridge axis, v transverse across ridge)
    cu, su = math.cos(ridge_angle_rad), math.sin(ridge_angle_rad)
    u = Xl * cu + Yl * su
    v = -Xl * su + Yl * cu
    # Trench cuts across ridge: narrow in u (half-width ~3.5m), extended in v (half-len ~11m)
    depth = -2.40 * np.exp(-(u / 3.4) ** 2) * np.exp(-(v / 11.0) ** 4)
    return z_bg + depth


def _make_rotational_slump_decoy(
    z_bg: np.ndarray,
    Xl: np.ndarray,
    Yl: np.ndarray,
    downslope_rad: float,
) -> np.ndarray:
    """Natural rotational slump: crescentic scarp + hummocky toe lobe open downslope."""
    cd, sd = math.cos(downslope_rad), math.sin(downslope_rad)
    s = Xl * cd + Yl * sd   # along downslope (+s = downhill)
    n = -Xl * sd + Yl * cd  # cross-slope
    # Scarp depression uphill (-s) and displaced toe mound downhill (+s), open downslope
    scarp = -1.1 * np.exp(-((s + 4.5) / 3.0) ** 2 - (n / 5.5) ** 2)
    lobe = 0.85 * np.exp(-((s - 4.0) / 3.5) ** 2 - (n / 5.0) ** 2)
    return z_bg + scarp + lobe


def _make_treethrow_decoy(
    z_bg: np.ndarray,
    Xl: np.ndarray,
    Yl: np.ndarray,
    downslope_rad: float,
) -> np.ndarray:
    """Natural tree-throw pit-mound pair (sub-scale, asymmetric, open)."""
    cd, sd = math.cos(downslope_rad), math.sin(downslope_rad)
    s = Xl * cd + Yl * sd
    n = -Xl * sd + Yl * cd
    pit = -0.60 * np.exp(-((s + 1.0) / 1.1) ** 2 - (n / 1.2) ** 2)
    mound = 0.60 * np.exp(-((s - 1.1) / 1.1) ** 2 - (n / 1.2) ** 2)
    return z_bg + pit + mound


def _make_fluvial_gully_decoy(
    z_bg: np.ndarray,
    Xl: np.ndarray,
    Yl: np.ndarray,
    downslope_rad: float,
) -> np.ndarray:
    """Natural steep fluvial gully aligned parallel (0 deg) to steepest downslope flow."""
    cd, sd = math.cos(downslope_rad), math.sin(downslope_rad)
    s = Xl * cd + Yl * sd
    n = -Xl * sd + Yl * cd
    # Elongated along downslope axis s, draining straight downhill
    gully = -1.65 * np.exp(-(n / 2.4) ** 2) * np.exp(-(s / 13.5) ** 4)
    return z_bg + gully


def _estimate_ridge_and_downslope(z_bg: np.ndarray, dx: float) -> tuple[float, float, float, float]:
    """Return (slope_deg, ridge_curvature, downslope_rad, ridge_axis_rad) at patch center."""
    zs = gaussian_filter(z_bg.astype(np.float64), sigma=6.0, mode="nearest")
    gy, gx = np.gradient(zs, dx)
    gyy, gyx = np.gradient(gy, dx)
    gxy, gxx = np.gradient(gx, dx)

    cy, cx = zs.shape[0] // 2, zs.shape[1] // 2
    sx, sy = float(gx[cy, cx]), float(gy[cy, cx])
    slope_deg = math.degrees(math.atan(math.hypot(sx, sy)))
    downslope_rad = math.atan2(-sy, -sx)

    # Hessian eigenvalues: most negative curvature -> cross-ridge; least negative -> ridge axis
    H = np.array([[float(gxx[cy, cx]), float(gxy[cy, cx])], [float(gyx[cy, cx]), float(gyy[cy, cx])]])
    vals, vecs = np.linalg.eigh(H)
    # Smallest eigenvalue (most negative) is cross-ridge; larger eigenvalue is ridge crest axis
    ridge_vec = vecs[:, 1]
    ridge_axis_rad = math.atan2(float(ridge_vec[1]), float(ridge_vec[0]))
    cross_curv = float(vals[0])  # < 0 on convex ridge crest
    return slope_deg, cross_curv, downslope_rad, ridge_axis_rad


def _rho_bin_name(rho: float) -> str:
    if rho < 1.0:
        return "[0.5, 1.0)"
    if rho < 2.5:
        return "[1.0, 2.5)"
    if rho < 5.0:
        return "[2.5, 5.0)"
    return ">= 5.0"


def _build_site_plan(
    tile_baselines: list[dict[str, Any]],
    seed: int = 202602,
) -> list[dict[str, Any]]:
    """Select 65 non-overlapping real forested sites across the 4 tiles:
    45 ruins (15 terrace, 15 mound_pit, 15 horikiri x {100, 300, 800} yr) + 20 natural decoys.
    Balances selection across rho_gnd strata and matches terrain suitability (ridges vs slopes).
    """
    rng = np.random.default_rng(seed)
    candidates: list[dict[str, Any]] = []

    for ti, tb in enumerate(tile_baselines):
        dtm = tb["dtm"].astype(np.float64)
        chm = tb["chm"].astype(np.float64)
        rho = tb["rho_gnd"].astype(np.float64)
        dx = tb["dx"]
        x0, y0 = tb["x0"], tb["y0"]
        ny, nx = dtm.shape

        # Candidate grid centers every 34 m, keeping 26 m away from tile borders
        for cy_m in range(26, int(ny * dx) - 26, 34):
            for cx_m in range(26, int(nx * dx) - 26, 34):
                r0 = int(round((cy_m - 20.0) / dx))
                r1 = int(round((cy_m + 20.0) / dx))
                c0 = int(round((cx_m - 20.0) / dx))
                c1 = int(round((cx_m + 20.0) / dx))
                patch_z = dtm[r0:r1, c0:c1]
                patch_chm = chm[r0:r1, c0:c1]
                patch_rho = rho[r0:r1, c0:c1]

                mean_chm = float(np.mean(patch_chm))
                mean_rho = float(np.mean(patch_rho))
                core_rho = float(np.mean(patch_rho[24:56, 24:56]))
                if mean_chm < 5.0 or mean_rho < 0.50 or core_rho < 0.50:
                    continue

                slope_deg, cross_curv, downslope_rad, ridge_rad = _estimate_ridge_and_downslope(patch_z, dx)
                candidates.append({
                    "tile_idx": ti,
                    "tile_id": tb["tile_id"],
                    "cx_rel": float(cx_m),
                    "cy_rel": float(cy_m),
                    "x_6676": x0 + float(cx_m),
                    "y_6676": y0 + float(cy_m),
                    "r0": r0, "r1": r1, "c0": c0, "c1": c1,
                    "mean_rho": core_rho,
                    "rho_bin": _rho_bin_name(core_rho),
                    "slope_deg": slope_deg,
                    "cross_curv": cross_curv,
                    "downslope_rad": downslope_rad,
                    "ridge_rad": ridge_rad,
                })

    rng.shuffle(candidates)
    used_indices: set[int] = set()

    def _pick_site(pred_fn, prefer_bins: list[str]) -> dict[str, Any]:
        for b in prefer_bins:
            for idx, c in enumerate(candidates):
                if idx not in used_indices and c["rho_bin"] == b and pred_fn(c):
                    used_indices.add(idx)
                    return dict(c)
        # Fallback ignoring bin preference if one bin is exhausted
        for idx, c in enumerate(candidates):
            if idx not in used_indices and pred_fn(c):
                used_indices.add(idx)
                return dict(c)
        # Ultimate fallback: any unused site
        for idx, c in enumerate(candidates):
            if idx not in used_indices:
                used_indices.add(idx)
                return dict(c)
        raise RuntimeError("Insufficient candidate forested patches in selected tiles")

    bins_cycle = ["[0.5, 1.0)", "[1.0, 2.5)", "[2.5, 5.0)", ">= 5.0"]
    plan: list[dict[str, Any]] = []
    ages = [100, 300, 800]

    # 15 terraces (5 per age) on steep slopes >= 19 deg
    for i in range(15):
        b_rot = bins_cycle[i % 4:] + bins_cycle[:i % 4]
        site = _pick_site(lambda c: c["slope_deg"] >= 19.0, b_rot)
        site.update({"kind": "ruin", "morphology": "terrace", "age_yr": ages[i // 5], "site_id": f"T2-TER-{i+1:02d}"})
        plan.append(site)

    # 15 mound_pit (5 per age) on slopes 8..34 deg
    for i in range(15):
        b_rot = bins_cycle[(i + 1) % 4:] + bins_cycle[:(i + 1) % 4]
        site = _pick_site(lambda c: 8.0 <= c["slope_deg"] <= 34.0, b_rot)
        site.update({"kind": "ruin", "morphology": "mound_pit", "age_yr": ages[i // 5], "site_id": f"T2-MP-{i+1:02d}"})
        plan.append(site)

    # 15 horikiri (5 per age) on convex ridge crests (most negative cross_curv, moderate ridge slope)
    # Sort unused candidates by convexity to favor true ridges
    for i in range(15):
        b_rot = bins_cycle[(i + 2) % 4:] + bins_cycle[:(i + 2) % 4]
        site = _pick_site(lambda c: c["cross_curv"] < -0.004 and c["slope_deg"] <= 28.0, b_rot)
        site.update({"kind": "ruin", "morphology": "horikiri", "age_yr": ages[i // 5], "site_id": f"T2-HOR-{i+1:02d}"})
        plan.append(site)

    # 20 natural decoys: 7 rotational slumps, 7 tree-throw pit-mounds, 6 fluvial gullies
    for i in range(7):
        b_rot = bins_cycle[i % 4:] + bins_cycle[:i % 4]
        site = _pick_site(lambda c: c["slope_deg"] >= 18.0, b_rot)
        site.update({"kind": "decoy", "morphology": "rotational_slump", "age_yr": 100, "site_id": f"T2-DEC-SLUMP-{i+1:02d}"})
        plan.append(site)

    for i in range(7):
        b_rot = bins_cycle[(i + 1) % 4:] + bins_cycle[:(i + 1) % 4]
        site = _pick_site(lambda c: c["slope_deg"] >= 10.0, b_rot)
        site.update({"kind": "decoy", "morphology": "treethrow", "age_yr": 100, "site_id": f"T2-DEC-TREE-{i+1:02d}"})
        plan.append(site)

    for i in range(6):
        b_rot = bins_cycle[(i + 2) % 4:] + bins_cycle[:(i + 2) % 4]
        site = _pick_site(lambda c: c["slope_deg"] >= 18.0, b_rot)
        site.update({"kind": "decoy", "morphology": "fluvial_gully", "age_yr": 100, "site_id": f"T2-DEC-GULLY-{i+1:02d}"})
        plan.append(site)

    return plan


def _build_weathered_delta(site: dict[str, Any], patch_z: np.ndarray, dx: float) -> np.ndarray:
    """Construct morphology on patch_z, evolve via Roering (1999) PDE, return smooth delta_h."""
    ny, nx = patch_z.shape
    xs = (np.arange(nx, dtype=np.float64) - nx / 2.0 + 0.5) * dx
    ys = (np.arange(ny, dtype=np.float64) - ny / 2.0 + 0.5) * dx
    Xl, Yl = np.meshgrid(xs, ys, indexing="xy")

    morph = site["morphology"]
    if morph == "terrace":
        z_target = _make_terrace_target(patch_z, Xl, Yl, radius_m=8.5)
    elif morph == "mound_pit":
        z_target = _make_mound_pit_target(patch_z, Xl, Yl, r_rim=5.5)
    elif morph == "horikiri":
        z_target = _make_horikiri_target(patch_z, Xl, Yl, site["ridge_rad"])
    elif morph == "rotational_slump":
        z_target = _make_rotational_slump_decoy(patch_z, Xl, Yl, site["downslope_rad"])
    elif morph == "treethrow":
        z_target = _make_treethrow_decoy(patch_z, Xl, Yl, site["downslope_rad"])
    elif morph == "fluvial_gully":
        z_target = _make_fluvial_gully_decoy(patch_z, Xl, Yl, site["downslope_rad"])
    else:
        raise ValueError(f"Unknown morphology {morph}")

    age = float(site["age_yr"])
    z_ev_feat = evolve_roering_1999(z_target, dx=dx, t_years=age, K=0.004, Sc=1.25)
    z_ev_bg = evolve_roering_1999(patch_z, dx=dx, t_years=age, K=0.004, Sc=1.25)
    delta_h = z_ev_feat - z_ev_bg

    # Taper cleanly to zero beyond r = 13..16 m to eliminate patch-border seams & neighbor overlap
    r = np.hypot(Xl, Yl)
    taper = np.clip(1.0 - (r - 13.0) / 3.0, 0.0, 1.0)
    return delta_h * taper


def run_self_test(cache_dir: Path | None = None) -> dict[str, Any]:
    """Validate Roering (1999) PDE physics (conservation, smoothing, nonlinear steepness effect)
    and real-LAZ ground-return injection pipeline without requiring `palimpsest/`.
    """
    if cache_dir is None:
        cache_dir = Path(__file__).resolve().parents[2] / "data" / "cache"

    # 1. PDE Physics Verification: mass conservation, monotonic diffusion, nonlinear acceleration
    dx = 0.5
    n = 80
    xs = (np.arange(n) - n / 2.0 + 0.5) * dx
    X, Y = np.meshgrid(xs, xs, indexing="xy")
    r = np.hypot(X, Y)
    z0 = 100.0 + 0.65 * X + np.where(r <= 6.0, 2.0, 0.0)  # steep slope + crisp pad
    z_100 = evolve_roering_1999(z0, dx, 100.0, K=0.004, Sc=1.25)
    z_300 = evolve_roering_1999(z0, dx, 300.0, K=0.004, Sc=1.25)
    z_800 = evolve_roering_1999(z0, dx, 800.0, K=0.004, Sc=1.25)
    # Linear diffusion comparison (Sc = 1e6)
    z_lin = evolve_roering_1999(z0, dx, 300.0, K=0.004, Sc=1e6)

    mass_err = abs(float(np.sum(z_800) - np.sum(z0))) / float(np.sum(np.abs(z0)))
    assert mass_err < 1e-10, f"Mass conservation failed: {mass_err}"

    max_slope_100 = float(np.max(np.hypot(*np.gradient(z_100, dx))))
    max_slope_300 = float(np.max(np.hypot(*np.gradient(z_300, dx))))
    max_slope_800 = float(np.max(np.hypot(*np.gradient(z_800, dx))))
    assert max_slope_100 > max_slope_300 > max_slope_800, "Max slope must decay monotonically with age"

    # Nonlinear diffusion on steep slope must smooth faster than linear diffusion
    diff_nonlin = float(np.linalg.norm(z_300 - z0))
    diff_lin = float(np.linalg.norm(z_lin - z0))
    assert diff_nonlin > diff_lin * 1.15, f"Nonlinear creep should exceed linear: {diff_nonlin} vs {diff_lin}"

    # 2. Real-LAZ injection sanity check on 1 real forested tile (08OC7888.laz)
    laz_path = cache_dir / "lidar" / DEFAULT_BENCHMARK_TILES[0]
    assert laz_path.exists(), f"Missing {laz_path}"
    las = laspy.read(str(laz_path))
    x = np.asarray(las.x, dtype=np.float64)
    y = np.asarray(las.y, dtype=np.float64)
    z = np.asarray(las.z, dtype=np.float64)
    x0 = float(math.floor(x.min() / 100.0) * 100.0)
    y0 = float(math.floor(y.min() / 100.0) * 100.0)

    # Extract a 60m x 60m real forested subpatch and run CSF + Roering injection
    sub = (x >= x0 + 80.0) & (x < x0 + 140.0) & (y >= y0 + 80.0) & (y < y0 + 140.0)
    xyz_sub = np.column_stack([x[sub], y[sub], z[sub]])
    gmask = _run_csf_mask(xyz_sub, use_palimpsest=False)
    dtm_sub, chm_sub, rho_sub = _grid_tile_from_points(
        xyz_sub[:, 0], xyz_sub[:, 1], xyz_sub[:, 2], gmask,
        x0 + 80.0, y0 + 80.0, 60.0, 60.0, dx=0.5,
    )
    patch_bg = dtm_sub[20:100, 20:100].astype(np.float64)
    delta_h = _build_weathered_delta(
        {"morphology": "terrace", "age_yr": 300, "ridge_rad": 0.0, "downslope_rad": 0.0},
        patch_bg, dx=0.5,
    )
    assert np.all(np.isfinite(delta_h)) and float(np.max(np.abs(delta_h))) > 0.2

    # Inject directly onto raw ground returns
    from scipy.ndimage import map_coordinates
    gx_rel = (xyz_sub[gmask, 0] - (x0 + 90.0)) / 0.5
    gy_rel = (xyz_sub[gmask, 1] - (y0 + 90.0)) / 0.5
    in_patch = (gx_rel >= 0) & (gx_rel < delta_h.shape[1] - 1) & (gy_rel >= 0) & (gy_rel < delta_h.shape[0] - 1)
    dz_pts = map_coordinates(delta_h, [gy_rel[in_patch], gx_rel[in_patch]], order=1, mode="nearest")
    assert np.all(np.isfinite(dz_pts)) and len(dz_pts) > 100

    rss_gb = psutil.Process(os.getpid()).memory_info().rss / (1024.0 ** 3)
    assert rss_gb < 4.0

    return {
        "status": "PASS",
        "mass_conservation_rel_err": mass_err,
        "max_slope_100_300_800": [max_slope_100, max_slope_300, max_slope_800],
        "nonlinear_vs_linear_l2": [diff_nonlin, diff_lin],
        "real_laz_injected_ground_pts": int(len(dz_pts)),
        "rss_gb": rss_gb,
    }


def _compute_derivatives_for_tile(dtm: np.ndarray, dx: float):
    from palimpsest.derivatives import (
        DerivativeBundle,
        compute_dinf_flow,
        compute_drainage_violation,
        compute_lrm,
        compute_openness,
        compute_rrim,
        compute_svf,
        compute_vat,
    )

    phi_10, psi_10, I_10 = compute_openness(dtm, dx, 10.0, n_azimuths=16)
    phi_25, psi_25, I_25 = compute_openness(dtm, dx, 25.0, n_azimuths=16)
    phi_50, psi_50, I_50 = compute_openness(dtm, dx, 50.0, n_azimuths=16)
    svf = compute_svf(dtm, dx, L=10.0, n_azimuths=16)
    lrm = compute_lrm(dtm, dx, radius_m=15.0)
    rrim_rgb = compute_rrim(dtm, dx, L=10.0, n_azimuths=16)
    vat_rgb = compute_vat(dtm, dx, L=10.0, n_azimuths=16)
    flow_ang, upslope, slope_rad = compute_dinf_flow(dtm, dx, fill_pits=False)
    drain_viol = compute_drainage_violation(dtm, flow_ang, upslope, slope_rad, dx)

    return DerivativeBundle(
        phi_10=phi_10, psi_10=psi_10, I_10=I_10,
        phi_25=phi_25, psi_25=psi_25, I_25=I_25,
        phi_50=phi_50, psi_50=psi_50, I_50=I_50,
        svf=svf, lrm=lrm, rrim_rgb=rrim_rgb, vat_rgb=vat_rgb,
        flow_angle_rad=flow_ang, upslope_area_m2=upslope,
        slope_rad=slope_rad, drainage_violation=drain_viol,
    )


def run_tier2_soil_creep(cache_dir: str | Path = "data/cache") -> dict[str, Any]:
    """Run full Tier-2 Roering (1999) 45-ruin + 20-decoy real-LAZ injection benchmark."""
    from palimpsest.detector import detect_candidates
    from scipy.ndimage import map_coordinates

    cache_dir = Path(cache_dir)
    dx = 0.5
    tile_baselines: list[dict[str, Any]] = []
    tile_point_clouds: list[dict[str, Any]] = []

    # 1. Load 4 real forested LAZ tiles and run CSF + baseline detection
    for tid in DEFAULT_BENCHMARK_TILES:
        laz_path = cache_dir / "lidar" / tid
        las = laspy.read(str(laz_path))
        x = np.asarray(las.x, dtype=np.float64)
        y = np.asarray(las.y, dtype=np.float64)
        z = np.asarray(las.z, dtype=np.float64)
        x0 = float(round(x.min() / 100.0) * 100.0)
        y0 = float(round(y.min() / 100.0) * 100.0)
        width_m, height_m = 400.0, 300.0

        xyz = np.column_stack([x, y, z])
        gmask = _run_csf_mask(xyz, use_palimpsest=True)
        dtm_bg, chm_bg, rho_bg = _grid_tile_from_points(x, y, z, gmask, x0, y0, width_m, height_m, dx=dx)
        deriv_bg = _compute_derivatives_for_tile(dtm_bg, dx)
        res_bg = detect_candidates(
            dtm_bg, chm_bg, rho_bg, deriv_bg,
            osm_vectors=None, gsi_layers=None,
            x0=x0, y0=y0, dx=dx, fdr_q=0.05, min_rho_gnd=0.5,
        )

        tile_baselines.append({
            "tile_id": tid,
            "x0": x0, "y0": y0,
            "width_m": width_m, "height_m": height_m,
            "dx": dx,
            "dtm": dtm_bg,
            "chm": chm_bg,
            "rho_gnd": rho_bg,
            "baseline_survivors": [(s.x_6676, s.y_6676) for s in res_bg.survivors],
        })
        tile_point_clouds.append({
            "x": x, "y": y, "z": z, "gmask": gmask,
        })

    # 2. Plan 45 ruins + 20 natural decoys across the 4 tiles
    plan = _build_site_plan(tile_baselines)

    # 3. Inject Roering-weathered delta_h directly onto raw ground returns in each tile
    for ti, tb in enumerate(tile_baselines):
        pc = tile_point_clouds[ti]
        x, y, z, gmask = pc["x"], pc["y"], pc["z"], pc["gmask"]
        sites_here = [s for s in plan if s["tile_idx"] == ti]

        for s in sites_here:
            patch_bg = tb["dtm"][s["r0"]:s["r1"], s["c0"]:s["c1"]].astype(np.float64)
            delta_h = _build_weathered_delta(s, patch_bg, dx=dx)

            px0 = tb["x0"] + s["c0"] * dx
            py0 = tb["y0"] + s["r0"] * dx
            pw = delta_h.shape[1] * dx
            ph = delta_h.shape[0] * dx

            # Find raw ground points inside this 40m x 40m injection patch
            in_p = gmask & (x >= px0) & (x < px0 + pw) & (y >= py0) & (y < py0 + ph)
            if np.any(in_p):
                gx_pix = (x[in_p] - px0) / dx - 0.5
                gy_pix = (y[in_p] - py0) / dx - 0.5
                dz_pts = map_coordinates(delta_h, [gy_pix, gx_pix], order=1, mode="nearest")
                z[in_p] += dz_pts

        # Re-run CSF on each modified 48m x 48m subpatch to verify end-to-end point classification
        for s in sites_here:
            px0 = tb["x0"] + max(0.0, s["cx_rel"] - 24.0)
            py0 = tb["y0"] + max(0.0, s["cy_rel"] - 24.0)
            in_box = (x >= px0) & (x < px0 + 48.0) & (y >= py0) & (y < py0 + 48.0)
            if np.sum(in_box) > 500:
                sub_xyz = np.column_stack([x[in_box], y[in_box], z[in_box]])
                sub_g = _run_csf_mask(sub_xyz, use_palimpsest=True)
                gmask[in_box] = sub_g

        # Re-grid modified full tile and run palimpsest derivatives + detector
        dtm_mod, chm_mod, rho_mod = _grid_tile_from_points(
            x, y, z, gmask, tb["x0"], tb["y0"], tb["width_m"], tb["height_m"], dx=dx
        )
        deriv_mod = _compute_derivatives_for_tile(dtm_mod, dx)
        res_mod = detect_candidates(
            dtm_mod, chm_mod, rho_mod, deriv_mod,
            osm_vectors=None, gsi_layers=None,
            x0=tb["x0"], y0=tb["y0"], dx=dx, fdr_q=0.05, min_rho_gnd=0.5,
        )
        tb["injected_survivors"] = res_mod.survivors
        tb["fdr_threshold"] = res_mod.fdr_threshold

        # Free raw arrays as soon as tile finishes to keep RSS << 4 GB
        pc.clear()

    # 4. Score TP, FP, FN, FDR, Precision, Recall breakdowns
    match_radius_m = 14.0
    ruins = [s for s in plan if s["kind"] == "ruin"]
    decoys = [s for s in plan if s["kind"] == "decoy"]

    ruin_hits: dict[str, bool] = {s["site_id"]: False for s in ruins}
    decoy_hits: dict[str, bool] = {s["site_id"]: False for s in decoys}
    bg_false_positives = 0
    max_q_survivors = 0.0

    for ti, tb in enumerate(tile_baselines):
        sites_here = [s for s in plan if s["tile_idx"] == ti]
        base_pts = tb["baseline_survivors"]
        for cand in tb["injected_survivors"]:
            max_q_survivors = max(max_q_survivors, float(cand.q_value))
            # Check match against injected sites first
            best_s = None
            best_d = 1e9
            for s in sites_here:
                d = math.hypot(cand.x_6676 - s["x_6676"], cand.y_6676 - s["y_6676"])
                if d <= match_radius_m and d < best_d:
                    best_d = d
                    best_s = s
            if best_s is not None:
                if best_s["kind"] == "ruin":
                    ruin_hits[best_s["site_id"]] = True
                else:
                    decoy_hits[best_s["site_id"]] = True
            else:
                # Exclude pre-existing baseline terrain survivors outside injected patches
                is_baseline = any(math.hypot(cand.x_6676 - bx, cand.y_6676 - by) <= match_radius_m for bx, by in base_pts)
                if not is_baseline:
                    bg_false_positives += 1

    tp = sum(1 for v in ruin_hits.values() if v)
    fn = len(ruins) - tp
    decoy_fp = sum(1 for v in decoy_hits.values() if v)
    fp = decoy_fp + bg_false_positives

    precision = tp / max(tp + fp, 1)
    recall = tp / len(ruins)
    empirical_fdr = fp / max(tp + fp, 1)

    def _breakdown(key_fn, keys_order):
        out = {}
        for k in keys_order:
            sub = [s for s in ruins if key_fn(s) == k]
            hits = sum(1 for s in sub if ruin_hits[s["site_id"]])
            out[str(k)] = {
                "total": len(sub),
                "detected": hits,
                "recall": (hits / len(sub)) if sub else None,
            }
        return out

    recall_by_class = _breakdown(lambda s: s["morphology"], ["terrace", "mound_pit", "horikiri"])
    recall_by_age = _breakdown(lambda s: s["age_yr"], [100, 300, 800])
    recall_by_rho = _breakdown(
        lambda s: s["rho_bin"],
        ["[0.5, 1.0)", "[1.0, 2.5)", "[2.5, 5.0)", ">= 5.0"],
    )

    rss_gb = psutil.Process(os.getpid()).memory_info().rss / (1024.0 ** 3)
    passed = (empirical_fdr <= 0.05) and (max_q_survivors <= 0.05) and (tp > 0) and (rss_gb < 4.0)

    return {
        "oracle": "tier2_soil_creep",
        "status": "PASS" if passed else "FAIL",
        "counts": {
            "ruins_injected": len(ruins),
            "decoys_injected": len(decoys),
            "tp": tp,
            "fn": fn,
            "decoy_fp": decoy_fp,
            "novel_background_fp": bg_false_positives,
            "fp_total": fp,
        },
        "metrics": {
            "empirical_fdr": empirical_fdr,
            "max_survivor_q_value": max_q_survivors,
            "precision": precision,
            "recall_overall": recall,
        },
        "recall_by_class": recall_by_class,
        "recall_by_age_yr": recall_by_age,
        "recall_by_rho_gnd": recall_by_rho,
        "peak_rss_gb": rss_gb,
    }
