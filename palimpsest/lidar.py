"""Chunked LiDAR streaming, Zhang et al. (2016) CSF filtering, and 0.5 m grid assembly."""

from __future__ import annotations

import gc
import json
import math
import os
import resource
import sys
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import CSF
import laspy
import numpy as np
from scipy.interpolate import LinearNDInterpolator
from scipy.ndimage import (distance_transform_edt, gaussian_filter, grey_opening,
                           map_coordinates, median_filter, uniform_filter)

_CWD_LOCK = threading.Lock()


@dataclass
class CSFParams:
    cloth_resolution: float = 0.75   # m, in [0.5, 1.0]
    rigidness: int = 2               # Zhang et al. (2016) steep-slope setting
    class_threshold: float = 0.30    # m, h_cc in [0.25, 0.40]
    b_sloop_smooth: bool = True      # slope post-processing enabled
    iterations: int = 500
    time_step: float = 0.65


@dataclass
class StudyZoneGrid:
    dtm: np.ndarray          # float32 (ny, nx), bare-earth z_gnd (m)
    dsm: np.ndarray          # float32 (ny, nx), first-return surface z_first (m)
    chm: np.ndarray          # float32 (ny, nx), max(0, dsm - dtm) (m)
    rho_gnd: np.ndarray      # float32 (ny, nx), ground return density (pts/m^2)
    x0: float                # SW corner X (EPSG:6676)
    y0: float                # SW corner Y (EPSG:6676)
    dx: float                # grid spacing (0.5 m)
    epsg: int                # 6676
    peak_rss_gb: float       # measured max RSS during streaming


def _peak_rss_gb() -> float:
    """Kernel process high-water RSS in GiB, including native allocations."""
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak * (1 if sys.platform == "darwin" else 1024) / 1024**3


def _terrain_normalized_returns(pts: np.ndarray, resolution: float):
    """Remove the broad hillside trend before fitting the inversion cloth.

    The lower envelope only supplies a coordinate transform. The final mask
    contains indices of original returns classified by the fine-scale CSF.
    """
    step = 3.0 * resolution
    origin = np.floor(pts[:, :2].min(axis=0) / step) * step
    nx, ny = (np.floor((pts[:, :2].max(axis=0) - origin) / step).astype(int) + 1)
    lower = np.full(nx * ny, np.inf)
    batch_size = 250_000
    for start in range(0, len(pts), batch_size):
        batch = pts[start:start+batch_size]
        col, row = np.floor((batch[:, :2] - origin) / step).astype(np.int32).T
        np.minimum.at(lower, row*nx + col, batch[:, 2])
    lower = lower.reshape(ny, nx)
    missing = ~np.isfinite(lower)
    if missing.any():
        nearest = distance_transform_edt(missing, return_distances=False, return_indices=True)
        lower = lower[tuple(nearest)]
    lower = median_filter(lower, size=3, mode="nearest")
    opened = grey_opening(lower, size=(5, 5), mode="nearest")
    trend = gaussian_filter(np.minimum(lower, opened + 2.0), 1.1, mode="nearest")
    residual = np.empty(len(pts), dtype=np.float64)
    for start in range(0, len(pts), batch_size):
        batch = pts[start:start+batch_size]
        col, row = ((batch[:, :2] - origin) / step - 0.5).T
        height = map_coordinates(trend, [row, col], order=1, mode="nearest")
        residual[start:start+len(batch)] = batch[:, 2] - height
    indices = np.flatnonzero(np.abs(residual) <= 3.0)
    normalized = pts[indices]
    normalized[:, 2] = residual[indices]
    return indices, normalized


def _cloth_ground_indices(pts: np.ndarray, params: CSFParams) -> np.ndarray:
    with _CWD_LOCK:
        orig_cwd = os.getcwd()
        with tempfile.TemporaryDirectory(prefix="palimpsest_csf_") as tmpdir:
            os.chdir(tmpdir)
            try:
                csf = CSF.CSF()
                csf.params.bSloopSmooth = bool(params.b_sloop_smooth)
                csf.params.cloth_resolution = float(params.cloth_resolution)
                csf.params.rigidness = int(params.rigidness)
                csf.params.class_threshold = float(params.class_threshold)
                csf.params.interations = int(params.iterations)
                csf.params.time_step = float(params.time_step)

                csf.setPointCloud(pts)
                ground = CSF.VecInt()
                non_ground = CSF.VecInt()
                try:
                    csf.do_filtering(ground, non_ground, False)
                except TypeError:
                    csf.do_filtering(ground, non_ground)
                gnd_idx = np.asarray(ground, dtype=np.int64)
            finally:
                os.chdir(orig_cwd)

    return gnd_idx[(gnd_idx >= 0) & (gnd_idx < len(pts))]


def run_csf_tile(
    xyz: np.ndarray,
    cloth_resolution: float = 0.75,
    rigidness: int = 2,
    class_threshold: float = 0.30,
    b_sloop_smooth: bool = True,
    iterations: int = 500,
    time_step: float = 0.65,
) -> np.ndarray:
    """Run Zhang et al. (2016) CSF on an (N, 3) float64 point array.

    Returns boolean ground mask of shape (N,) where True = ground return.
    Always executes CSF.do_filtering inside a TemporaryDirectory so any
    auxiliary CWD output (e.g. cloth_nodes.txt) never pollutes the repo.
    """
    pts = np.asarray(xyz, dtype=np.float64)
    if pts.ndim != 2 or pts.shape[1] != 3:
        raise ValueError(f"Expected xyz of shape (N, 3), got {pts.shape}")
    n_pts = pts.shape[0]
    if n_pts == 0:
        return np.zeros(0, dtype=bool)
    if n_pts < 8:
        return np.ones(n_pts, dtype=bool)

    span_x = float(np.max(pts[:, 0]) - np.min(pts[:, 0]))
    span_y = float(np.max(pts[:, 1]) - np.min(pts[:, 1]))
    if span_x < 1e-6 or span_y < 1e-6:
        z_min = float(np.min(pts[:, 2]))
        return (pts[:, 2] - z_min) <= float(class_threshold)

    source_indices, pts = _terrain_normalized_returns(pts, cloth_resolution)
    if len(pts) < 8:
        return np.zeros(n_pts, dtype=bool)

    params = CSFParams(cloth_resolution, rigidness, class_threshold, b_sloop_smooth, iterations, time_step)
    gnd_idx = _cloth_ground_indices(pts, params)
    mask = np.zeros(n_pts, dtype=bool)
    mask[source_indices[gnd_idx]] = True
    return mask


def _discover_tiles(cache_dir: Path) -> tuple[list[dict], tuple[float, float, float, float] | None, int]:
    lidar_dir = cache_dir / "lidar"
    if not lidar_dir.is_dir():
        lidar_dir = cache_dir

    study_zone_path = cache_dir / "study_zone.json"
    bounds = None
    epsg = 6676
    if study_zone_path.is_file():
        with open(study_zone_path, "r", encoding="utf-8") as f:
            sz = json.load(f)
        if "bounds_epsg6676" in sz and len(sz["bounds_epsg6676"]) == 4:
            b = [float(v) for v in sz["bounds_epsg6676"]]
            bounds = (b[0], b[1], b[2], b[3])
        epsg = int(sz.get("epsg", 6676))

    meta_path = cache_dir / "lidar_tiles_meta.json"
    tiles: list[dict] = []
    if meta_path.is_file():
        with open(meta_path, "r", encoding="utf-8") as f:
            raw_meta = json.load(f)
        for entry in raw_meta:
            tid = entry["tile_id"]
            p = lidar_dir / f"{tid}.laz"
            if not p.is_file():
                p = lidar_dir / f"{tid}.las"
            if p.is_file():
                tiles.append({
                    "path": str(p),
                    "mins": [float(v) for v in entry["mins"]],
                    "maxs": [float(v) for v in entry["maxs"]],
                })

    if not tiles:
        laz_files = sorted(list(lidar_dir.glob("*.laz")) + list(lidar_dir.glob("*.las")))
        for p in laz_files:
            with laspy.open(p) as fh:
                h = fh.header
                tiles.append({
                    "path": str(p),
                    "mins": [float(h.mins[0]), float(h.mins[1]), float(h.mins[2])],
                    "maxs": [float(h.maxs[0]), float(h.maxs[1]), float(h.maxs[2])],
                })

    if not tiles:
        raise FileNotFoundError(f"No .laz or .las tiles found under {cache_dir}")

    if bounds is None:
        min_x = min(t["mins"][0] for t in tiles)
        min_y = min(t["mins"][1] for t in tiles)
        max_x = max(t["maxs"][0] for t in tiles)
        max_y = max(t["maxs"][1] for t in tiles)
        bounds = (min_x, min_y, max_x, max_y)

    return tiles, bounds, epsg


def _process_chunk(task: dict) -> dict:
    """Process one core chunk + halo in an isolated worker/function."""
    cx0 = task["cx0"]
    cy0 = task["cy0"]
    cx1 = task["cx1"]
    cy1 = task["cy1"]
    halo_m = task["halo_m"]
    dx = task["dx"]
    csf_dict = task["csf_params"]
    tile_paths = task["tile_paths"]
    row_start = task["row_start"]
    col_start = task["col_start"]
    ch_ny = task["ch_ny"]
    ch_nx = task["ch_nx"]

    hx0 = cx0 - halo_m
    hy0 = cy0 - halo_m
    hx1 = cx1 + halo_m
    hy1 = cy1 + halo_m

    xs_parts: list[np.ndarray] = []
    ys_parts: list[np.ndarray] = []
    zs_parts: list[np.ndarray] = []

    for tp in tile_paths:
        with laspy.open(tp) as fh:
            for chunk in fh.chunk_iterator(1_000_000):
                px = np.asarray(chunk.x, dtype=np.float64)
                py = np.asarray(chunk.y, dtype=np.float64)
                mask = (px >= hx0) & (px < hx1) & (py >= hy0) & (py < hy1)
                if np.any(mask):
                    xs_parts.append(px[mask])
                    ys_parts.append(py[mask])
                    zs_parts.append(np.asarray(chunk.z, dtype=np.float64)[mask])

    gnd_sum = np.zeros((ch_ny, ch_nx), dtype=np.float64)
    gnd_cnt = np.zeros((ch_ny, ch_nx), dtype=np.int32)
    dsm_max = np.full((ch_ny, ch_nx), -np.inf, dtype=np.float32)

    if xs_parts:
        xyz = np.empty((sum(len(part) for part in xs_parts), 3), dtype=np.float64)
        start = 0
        for xs, ys, zs in zip(xs_parts, ys_parts, zs_parts):
            end = start + len(xs)
            xyz[start:end, 0] = xs
            xyz[start:end, 1] = ys
            xyz[start:end, 2] = zs
            start = end
        del xs, ys, zs
        del xs_parts, ys_parts, zs_parts

        gnd_mask = run_csf_tile(
            xyz,
            cloth_resolution=csf_dict["cloth_resolution"],
            rigidness=csf_dict["rigidness"],
            class_threshold=csf_dict["class_threshold"],
            b_sloop_smooth=csf_dict["b_sloop_smooth"],
            iterations=csf_dict["iterations"],
            time_step=csf_dict["time_step"],
        )
        hx, hy, hz = xyz.T

        in_core = (hx >= cx0) & (hx < cx1) & (hy >= cy0) & (hy < cy1)
        if np.any(in_core):
            cx_pts = hx[in_core]
            cy_pts = hy[in_core]
            cz_pts = hz[in_core]
            cg_pts = gnd_mask[in_core]

            cols = np.floor((cx_pts - cx0) / dx).astype(np.int32)
            rows = np.floor((cy_pts - cy0) / dx).astype(np.int32)
            valid_rc = (rows >= 0) & (rows < ch_ny) & (cols >= 0) & (cols < ch_nx)
            rows = rows[valid_rc]
            cols = cols[valid_rc]
            cz_pts = cz_pts[valid_rc]
            cg_pts = cg_pts[valid_rc]

            flat = rows * ch_nx + cols
            np.maximum.at(dsm_max.ravel(), flat, cz_pts.astype(np.float32))

            if np.any(cg_pts):
                g_flat = flat[cg_pts]
                g_z = cz_pts[cg_pts]
                np.add.at(gnd_sum.ravel(), g_flat, g_z)
                np.add.at(gnd_cnt.ravel(), g_flat, 1)

        del hx, hy, hz, xyz, gnd_mask

    gc.collect()
    return {
        "row_start": row_start,
        "col_start": col_start,
        "ch_ny": ch_ny,
        "ch_nx": ch_nx,
        "gnd_sum": gnd_sum,
        "gnd_cnt": gnd_cnt,
        "dsm_max": dsm_max,
    }


def _interpolate_empty_cells_tiled(
    dtm_raw: np.ndarray,
    tile_cells: int = 500,
    halo_cells: int = 100,
) -> np.ndarray:
    """Linear TIN interpolation ONLY over empty ground cells, processed in overlapping tiles."""
    ny, nx = dtm_raw.shape
    valid_global = np.isfinite(dtm_raw)
    if np.all(valid_global):
        return dtm_raw.astype(np.float32)
    if not np.any(valid_global):
        return np.zeros((ny, nx), dtype=np.float32)

    out = dtm_raw.copy()
    n_valid_total = int(np.count_nonzero(valid_global))
    if n_valid_total < 4:
        _, idx = distance_transform_edt(~valid_global, return_indices=True)
        return dtm_raw[idx[0], idx[1]].astype(np.float32)

    for r0 in range(0, ny, tile_cells):
        r1 = min(ny, r0 + tile_cells)
        pr0 = max(0, r0 - halo_cells)
        pr1 = min(ny, r1 + halo_cells)
        for c0 in range(0, nx, tile_cells):
            c1 = min(nx, c0 + tile_cells)
            core_miss = ~np.isfinite(dtm_raw[r0:r1, c0:c1])
            if not np.any(core_miss):
                continue
            pc0 = max(0, c0 - halo_cells)
            pc1 = min(nx, c1 + halo_cells)

            sub = dtm_raw[pr0:pr1, pc0:pc1]
            sub_valid = np.isfinite(sub)
            n_val = int(np.count_nonzero(sub_valid))
            mr, mc = np.nonzero(core_miss)
            if n_val >= 4:
                vr, vc = np.nonzero(sub_valid)
                pts = np.column_stack((vr + pr0, vc + pc0)).astype(np.float64)
                vals = sub[vr, vc].astype(np.float64)
                interp = LinearNDInterpolator(pts, vals)
                filled = interp(mr + r0, mc + c0).astype(np.float32)
                ok = np.isfinite(filled)
                out[mr[ok] + r0, mc[ok] + c0] = filled[ok]

    # Fill any convex-hull border NaNs via nearest observed cell
    still_miss = ~np.isfinite(out)
    if np.any(still_miss):
        _, idx = distance_transform_edt(still_miss, return_indices=True)
        out[still_miss] = out[idx[0][still_miss], idx[1][still_miss]]

    return out.astype(np.float32)


def stream_study_zone(
    cache_dir: str | Path,
    chunk_size_m: float = 500.0,
    halo_m: float = 50.0,
    dx: float = 0.5,
    csf_params: CSFParams | None = None,
    rss_limit_gb: float = 4.0,
) -> StudyZoneGrid:
    """Stream all cached LAZ tiles in 500m x 500m chunks + 50m halos,
    enforcing host RSS < rss_limit_gb.
    """
    cache_path = Path(cache_dir)
    params = csf_params or CSFParams()
    tiles, bounds, epsg = _discover_tiles(cache_path)
    x0, y0, x1, y1 = bounds

    nx = int(round((x1 - x0) / dx))
    ny = int(round((y1 - y0) / dx))

    dtm_raw = np.full((ny, nx), np.nan, dtype=np.float32)
    dsm_raw = np.full((ny, nx), np.nan, dtype=np.float32)
    gnd_cnt_global = np.zeros((ny, nx), dtype=np.int32)

    csf_dict = {
        "cloth_resolution": float(params.cloth_resolution),
        "rigidness": int(params.rigidness),
        "class_threshold": float(params.class_threshold),
        "b_sloop_smooth": bool(params.b_sloop_smooth),
        "iterations": int(params.iterations),
        "time_step": float(params.time_step),
    }

    tasks: list[dict] = []
    cy = y0
    while cy < y1 - 1e-6:
        cy_end = min(y1, cy + chunk_size_m)
        row_start = int(round((cy - y0) / dx))
        row_end = int(round((cy_end - y0) / dx))
        ch_ny = row_end - row_start
        cx = x0
        while cx < x1 - 1e-6:
            cx_end = min(x1, cx + chunk_size_m)
            col_start = int(round((cx - x0) / dx))
            col_end = int(round((cx_end - x0) / dx))
            ch_nx = col_end - col_start

            hx0 = cx - halo_m
            hy0 = cy - halo_m
            hx1 = cx_end + halo_m
            hy1 = cy_end + halo_m
            hit_tiles = [
                t["path"]
                for t in tiles
                if not (
                    t["maxs"][0] < hx0
                    or t["mins"][0] > hx1
                    or t["maxs"][1] < hy0
                    or t["mins"][1] > hy1
                )
            ]
            if hit_tiles and ch_ny > 0 and ch_nx > 0:
                tasks.append({
                    "cx0": cx,
                    "cy0": cy,
                    "cx1": cx_end,
                    "cy1": cy_end,
                    "halo_m": halo_m,
                    "dx": dx,
                    "csf_params": csf_dict,
                    "tile_paths": hit_tiles,
                    "row_start": row_start,
                    "col_start": col_start,
                    "ch_ny": ch_ny,
                    "ch_nx": ch_nx,
                })
            cx = cx_end
        cy = cy_end

    peak_rss_gb = _peak_rss_gb()

    def _commit(res: dict) -> None:
        r0 = res["row_start"]
        c0 = res["col_start"]
        r1 = r0 + res["ch_ny"]
        c1 = c0 + res["ch_nx"]
        cnt = res["gnd_cnt"]
        gsum = res["gnd_sum"]
        dmax = res["dsm_max"]

        gnd_cnt_global[r0:r1, c0:c1] = cnt
        has_g = cnt > 0
        if np.any(has_g):
            sub_dtm = dtm_raw[r0:r1, c0:c1]
            sub_dtm[has_g] = (gsum[has_g] / cnt[has_g]).astype(np.float32)

        has_d = np.isfinite(dmax)
        if np.any(has_d):
            sub_dsm = dsm_raw[r0:r1, c0:c1]
            sub_dsm[has_d] = dmax[has_d]

    # Native CSF allocations peak inside the solve. Process one window at
    # a time so these peaks cannot overlap across workers.
    for task in tasks:
        res = _process_chunk(task)
        _commit(res)
        del res
        gc.collect()
        peak_rss_gb = max(peak_rss_gb, _peak_rss_gb())
        if peak_rss_gb * 1024**3 >= rss_limit_gb * 1e9:
            raise MemoryError(f"LiDAR streaming reached {peak_rss_gb:.3f} GiB")
    
    # Ground point density map (pts/m^2) over 7x7 cell neighborhood (3.5m x 3.5m = 12.25 m^2)
    cell_area = float(dx * dx)
    raw_density = gnd_cnt_global.astype(np.float32) / np.float32(cell_area)
    rho_gnd = uniform_filter(raw_density, size=7, mode="nearest").astype(np.float32)
    del gnd_cnt_global, raw_density
    gc.collect()

    # Linear TIN interpolation strictly over empty DTM cells
    dtm = _interpolate_empty_cells_tiled(dtm_raw, tile_cells=500, halo_cells=100)
    del dtm_raw
    gc.collect()

    # Fill empty DSM cells (if any) via nearest valid or fallback to DTM
    dsm_miss = ~np.isfinite(dsm_raw)
    if np.any(dsm_miss):
        if np.any(~dsm_miss):
            _, idx = distance_transform_edt(dsm_miss, return_indices=True)
            dsm_raw[dsm_miss] = dsm_raw[idx[0][dsm_miss], idx[1][dsm_miss]]
        else:
            dsm_raw[:] = dtm
    dsm = np.maximum(dsm_raw, dtm).astype(np.float32)
    del dsm_raw
    gc.collect()

    chm = np.maximum(0.0, dsm - dtm).astype(np.float32)
    peak_rss_gb = max(peak_rss_gb, _peak_rss_gb())

    return StudyZoneGrid(
        dtm=dtm,
        dsm=dsm,
        chm=chm,
        rho_gnd=rho_gnd,
        x0=float(x0),
        y0=float(y0),
        dx=float(dx),
        epsg=epsg,
        peak_rss_gb=float(peak_rss_gb),
    )


def extract_cutout_points(
    cache_dir: str | Path,
    cutouts: Iterable[tuple[str, float, float, float]],
    dtm: np.ndarray,
    x0_grid: float,
    y0_grid: float,
    dx: float,
    max_pts: int = 150_000,
    seed: int = 42,
) -> dict[str, np.ndarray]:
    """Extract subsampled 3D canopy + ground points for 200m x 200m cutouts
    in a bounded-memory pass over only intersecting LAZ tiles.

    Each cutout item is (candidate_id, cut_x0, cut_y0, size_m).
    Returns dict mapping candidate_id -> float32 array of shape (M, 4):
    [rel_x, rel_y, z_abs, hag].
    """
    cache_path = Path(cache_dir)
    tiles, _, _ = _discover_tiles(cache_path)
    cutout_list = list(cutouts)
    if not cutout_list:
        return {}

    ny, nx = dtm.shape
    rng = np.random.default_rng(seed)
    acc: dict[str, dict[str, list[np.ndarray]]] = {
        cid: {"x": [], "y": [], "z": []} for cid, _, _, _ in cutout_list
    }

    # Build tile -> cutout mapping so each LAZ file is opened at most once
    tile_to_cuts: list[tuple[dict, list[tuple[str, float, float, float]]]] = []
    for t in tiles:
        matched = [
            c for c in cutout_list
            if not (
                t["maxs"][0] < c[1]
                or t["mins"][0] > c[1] + c[3]
                or t["maxs"][1] < c[2]
                or t["mins"][1] > c[2] + c[3]
            )
        ]
        if matched:
            tile_to_cuts.append((t, matched))

    for t, matched_cuts in tile_to_cuts:
        with laspy.open(t["path"]) as fh:
            for chunk in fh.chunk_iterator(1_000_000):
                px = np.asarray(chunk.x, dtype=np.float64)
                py = np.asarray(chunk.y, dtype=np.float64)
                pz = np.asarray(chunk.z, dtype=np.float64)
                for cid, cx0, cy0, size_m in matched_cuts:
                    m = (
                        (px >= cx0)
                        & (px < cx0 + size_m)
                        & (py >= cy0)
                        & (py < cy0 + size_m)
                    )
                    if np.any(m):
                        sub_x = px[m]
                        sub_y = py[m]
                        sub_z = pz[m]
                        # Early stride if a single chunk already exceeds 2x max_pts
                        if sub_x.size > max_pts:
                            stride = max(1, sub_x.size // max_pts)
                            sub_x = sub_x[::stride]
                            sub_y = sub_y[::stride]
                            sub_z = sub_z[::stride]
                        acc[cid]["x"].append(sub_x)
                        acc[cid]["y"].append(sub_y)
                        acc[cid]["z"].append(sub_z)

    result: dict[str, np.ndarray] = {}
    for cid, cx0, cy0, _size_m in cutout_list:
        parts = acc[cid]
        if not parts["x"]:
            result[cid] = np.zeros((0, 4), dtype=np.float32)
            continue
        ax = np.concatenate(parts["x"])
        ay = np.concatenate(parts["y"])
        az = np.concatenate(parts["z"])
        del parts["x"][:], parts["y"][:], parts["z"][:]

        n_total = ax.size
        if n_total > max_pts:
            keep = rng.choice(n_total, size=max_pts, replace=False)
            keep.sort()
            ax = ax[keep]
            ay = ay[keep]
            az = az[keep]

        # Bilinear lookup of z_gnd for accurate HAG
        rf = np.clip((ay - y0_grid) / dx - 0.5, 0.0, ny - 1.0001)
        cf = np.clip((ax - x0_grid) / dx - 0.5, 0.0, nx - 1.0001)
        r0 = np.floor(rf).astype(np.int32)
        c0 = np.floor(cf).astype(np.int32)
        fr = rf - r0
        fc = cf - c0
        zg = (
            (1.0 - fr) * ((1.0 - fc) * dtm[r0, c0] + fc * dtm[r0, c0 + 1])
            + fr * ((1.0 - fc) * dtm[r0 + 1, c0] + fc * dtm[r0 + 1, c0 + 1])
        )
        hag = np.maximum(0.0, az - zg)
        pts_out = np.column_stack((
            (ax - cx0).astype(np.float32),
            (ay - cy0).astype(np.float32),
            az.astype(np.float32),
            hag.astype(np.float32),
        )).astype(np.float32, copy=False)
        result[cid] = np.ascontiguousarray(pts_out)

    gc.collect()
    return result
