"""End-to-end PALIMPSEST CLI pipeline (`python -m palimpsest.pipeline`)."""

from __future__ import annotations

import argparse
import gc
import json
import time
from pathlib import Path

import numpy as np

from palimpsest.coverage import finish_field_map, write_candidate_support, write_density_map
from palimpsest.derivatives import compute_all_derivatives
from palimpsest.detector import CandidateRecord, detect_candidates
from palimpsest.export import (
    build_gsi_sampler,
    crop_gsi_textures,
    write_binary_pack,
    write_candidates_json,
    write_waypoints_gpx,
)
from palimpsest.lidar import CSFParams, _peak_rss_gb, extract_cutout_points, stream_study_zone
from palimpsest.provenance import confirm_raw_ground


def _select_pack_candidates(
    survivors: list[CandidateRecord],
    all_candidates: list[CandidateRecord],
    max_rejected_packs: int = 12,
) -> list[CandidateRecord]:
    selected: list[CandidateRecord] = list(survivors)
    rejected = [c for c in all_candidates if c.status == "rejected"]

    # Pick representative rejected artifacts across diverse rejection reasons
    by_reason: dict[str, list[CandidateRecord]] = {}
    for c in rejected:
        key = c.rejection_reason or "unknown"
        by_reason.setdefault(key, []).append(c)

    picked_rej: list[CandidateRecord] = []
    reason_order = ["forestry_switchback", "osm_modern", "natural_thalweg", "fdr_rejected", "low_rho_gnd"]
    idx = 0
    while len(picked_rej) < max_rejected_packs:
        progressed = False
        for rkey in reason_order + [k for k in by_reason if k not in reason_order]:
            bucket = by_reason.get(rkey, [])
            if idx < len(bucket):
                picked_rej.append(bucket[idx])
                progressed = True
                if len(picked_rej) >= max_rejected_packs:
                    break
        if not progressed:
            break
        idx += 1

    return selected + picked_rej


def run_pipeline(
    cache_dir: str | Path = "data/cache",
    out_dir: str | Path = "data/output",
    pack_size_m: float = 200.0,
    max_canopy_pts: int = 150_000,
) -> dict:
    t0 = time.perf_counter()
    cache_path = Path(cache_dir)
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    (out_path / "packs").mkdir(parents=True, exist_ok=True)

    study_zone = {}
    sz_path = cache_path / "study_zone.json"
    if sz_path.is_file():
        with open(sz_path, "r", encoding="utf-8") as fh:
            study_zone = json.load(fh)

    print(f"[PALIMPSEST] Streaming LiDAR from {cache_path} ...")
    grid = stream_study_zone(
        cache_dir=cache_path,
        chunk_size_m=500.0,
        halo_m=50.0,
        dx=0.5,
        csf_params=CSFParams(),
        rss_limit_gb=4.0,
    )
    write_density_map(out_path, grid)
    t_csf = time.perf_counter()
    print(
        f"[PALIMPSEST] Grid ready: shape={grid.dtm.shape}, CHM_max={grid.chm.max():.1f}m, "
        f"peak_rss={grid.peak_rss_gb:.3f} GiB ({t_csf - t0:.1f}s)"
    )

    print("[PALIMPSEST] Computing multi-scale terrain derivatives & D-infinity flow ...")
    derivs = compute_all_derivatives(grid.dtm, dx=grid.dx, n_azimuths=16, fill_pits=False)
    t_deriv = time.perf_counter()
    peak_rss = max(grid.peak_rss_gb, _peak_rss_gb())
    print(f"[PALIMPSEST] Derivatives complete ({t_deriv - t_csf:.1f}s), peak_rss={peak_rss:.3f} GiB")

    # Load OSM & historic anchors
    osm_vectors: dict = {}
    osm_path = cache_path / "osm" / "osm_features.json"
    if osm_path.is_file():
        with open(osm_path, "r", encoding="utf-8") as fh:
            osm_vectors = json.load(fh)
    hist_path = cache_path / "osm" / "historic_anchors.json"
    if hist_path.is_file():
        with open(hist_path, "r", encoding="utf-8") as fh:
            hist_data = json.load(fh)
        osm_vectors["osm_historic_and_peak_features"] = hist_data.get("osm_historic_and_peak_features", [])

    gsi_layers = build_gsi_sampler(cache_path)

    print("[PALIMPSEST] Running 3-morphology detector, provenance gate, BH-FDR, and falsifiers ...")
    detection = detect_candidates(
        grid.dtm,
        grid.chm,
        grid.rho_gnd,
        derivs,
        osm_vectors=osm_vectors,
        gsi_layers=gsi_layers,
        x0=grid.x0,
        y0=grid.y0,
        dx=grid.dx,
        fdr_q=0.05,
        min_rho_gnd=0.5,
    )
    confirm_raw_ground(detection, grid, cache_path)
    write_candidate_support(out_path, grid, detection)
    print(f"[PALIMPSEST] Funnel: {detection.funnel}")

    # Export binary packs + GSI textures for top survivors & representative rejected artifacts
    pack_targets = _select_pack_candidates(detection.survivors, detection.candidates)
    ny, nx = grid.dtm.shape
    cut_cells = int(round(pack_size_m / grid.dx))
    half_m = 0.5 * pack_size_m

    cutouts_meta: list[tuple[CandidateRecord, int, int, float, float]] = []

    for rec in pack_targets:
        c0 = int(round((rec.x_6676 - half_m - grid.x0) / grid.dx))
        r0 = int(round((rec.y_6676 - half_m - grid.y0) / grid.dx))
        c0 = max(0, min(nx - cut_cells, c0))
        r0 = max(0, min(ny - cut_cells, r0))
        cut_x0 = grid.x0 + c0 * grid.dx
        cut_y0 = grid.y0 + r0 * grid.dx
        cutouts_meta.append((rec, r0, c0, cut_x0, cut_y0))

    # Bound raw cutout buffers even when neighboring candidates overlap.
    cutouts_meta.sort(key=lambda item: (item[1] // cut_cells, item[2]))
    print(f"[PALIMPSEST] Exporting {len(cutouts_meta)} candidate packs ...")
    for start in range(0, len(cutouts_meta), 6):
        batch = cutouts_meta[start:start+6]
        cutout_requests = [(rec.candidate_id, x, y, pack_size_m) for rec, _, _, x, y in batch]
        canopy_clouds = extract_cutout_points(
            cache_dir=cache_path,
            cutouts=cutout_requests,
            dtm=grid.dtm,
            x0_grid=grid.x0,
            y0_grid=grid.y0,
            dx=grid.dx,
            max_pts=max_canopy_pts,
        )

        for rec, r0, c0, cut_x0, cut_y0 in batch:
            r1 = r0 + cut_cells
            c1 = c0 + cut_cells
            rrim_sub = derivs.rrim_rgb[r0:r1, c0:c1].astype(np.float32) / 255.0
            layers = {
                "z_gnd": grid.dtm[r0:r1, c0:c1],
                "chm": grid.chm[r0:r1, c0:c1],
                "rho_gnd": grid.rho_gnd[r0:r1, c0:c1],
                "rrim_r": rrim_sub[..., 0],
                "rrim_g": rrim_sub[..., 1],
                "rrim_b": rrim_sub[..., 2],
                "svf": derivs.svf[r0:r1, c0:c1],
                "lrm": derivs.lrm[r0:r1, c0:c1],
                "openness_diff": derivs.I_10[r0:r1, c0:c1],
                "flow_violation": derivs.drainage_violation[r0:r1, c0:c1],
            }
            pack_rel = f"packs/{rec.candidate_id}.bin"
            write_binary_pack(
                out_path / pack_rel,
                x0=cut_x0,
                y0=cut_y0,
                dx=grid.dx,
                layers=layers,
                canopy_pts=canopy_clouds.get(rec.candidate_id, np.zeros((0, 4), dtype=np.float32)),
            )
            rec.pack_file = pack_rel
            rec.textures = crop_gsi_textures(
                cache_dir=cache_path,
                out_dir=out_path,
                candidate_id=rec.candidate_id,
                x0_cut=cut_x0,
                y0_cut=cut_y0,
                size_m=pack_size_m,
                tex_px=256,
            )

    gpx_path = write_waypoints_gpx(
        out_path / "palimpsest_waypoints.gpx",
        detection.survivors,
        grid.dtm,
        grid.x0,
        grid.y0,
        grid.dx,
    )

    del grid, derivs
    finish_field_map(out_path, cache_path, detection)
    peak_rss = max(peak_rss, _peak_rss_gb())
    if peak_rss * 1024**3 >= 4_000_000_000:
        raise MemoryError(f"Basin export reached {peak_rss:.3f} GiB")
    json_path = write_candidates_json(out_path / "candidates.json", detection, study_zone,
                                      fdr_q=0.05, peak_rss_gb=peak_rss)
    gc.collect()
    total_s = time.perf_counter() - t0
    print(
        f"[PALIMPSEST] Done in {total_s:.1f}s | survivors={len(detection.survivors)} | "
        f"packs={len(cutouts_meta)} | peak_rss={peak_rss:.3f} GiB"
    )
    print(f"[PALIMPSEST] Wrote {json_path} and {gpx_path}")

    return {
        "funnel": detection.funnel,
        "survivors": len(detection.survivors),
        "packs": len(cutouts_meta),
        "peak_rss_gb": peak_rss,
        "elapsed_s": total_s,
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="PALIMPSEST LiDAR Archaeological Prospection Pipeline")
    parser.add_argument("--cache", default="data/cache", help="Path to data/cache")
    parser.add_argument("--out", default="data/output", help="Path to data/output")
    parser.add_argument("--pack-size-m", type=float, default=200.0, help="Cutout edge length in meters")
    parser.add_argument("--max-canopy-pts", type=int, default=150000, help="Max subsampled canopy points per pack")
    args = parser.parse_args(argv)
    run_pipeline(
        cache_dir=args.cache,
        out_dir=args.out,
        pack_size_m=args.pack_size_m,
        max_canopy_pts=args.max_canopy_pts,
    )


if __name__ == "__main__":
    main()
