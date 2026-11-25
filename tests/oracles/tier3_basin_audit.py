"""Tier 3 Real-Basin Adversarial Audit for PALIMPSEST.

Independently audits real-basin pipeline outputs under `data/output/` against
raw immutable ground truth in `data/cache/`:
1. Binary Tile Pack Audit (`CONTRACT.md` §4): PLMP v1 header, exact byte size,
   finite floats, coordinate containment, and layer bounds.
2. Raw Ground-Point Count Audit: Re-reads raw `.laz` files around every
   survivor's (x_6676, y_6676) and counts raw LAS class-2 + local CSF ground
   points directly, verifying true rho_gnd >= 0.5 pts/m^2 (no TIN hallucinations).
3. OSM Modern Infrastructure Audit: Cross-checks Class A / Class B survivors
   against `data/cache/osm/osm_features.json` roads, buildings, power towers,
   and modern structures with a 15 m buffer using exact Shapely geometry.
4. GSI Historical Aerial Audit: Checks `textures` (`ort_USA10` is None),
   verifies image readability & pixel variance (non-blank) via `rasterio`.
5. GPX Audit: Validates GPX 1.1 XML, survivor coverage, and EPSG:6676 -> WGS84
   coordinate agreement within < 0.5 m.
6. Cache Manifest & Memory Audit: Verifies `data/cache/MANIFEST.sha256` intact
   and monitors peak RSS < 4.0 GB.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import struct
import warnings
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import laspy
import numpy as np
import psutil
import rasterio
from pyproj import Transformer
from shapely.geometry import LineString, Point, Polygon


_TO_6676 = Transformer.from_crs("EPSG:4326", "EPSG:6676", always_xy=True)
_TO_WGS84 = Transformer.from_crs("EPSG:6676", "EPSG:4326", always_xy=True)

_MODERN_HIGHWAY_TYPES = {
    "motorway", "trunk", "primary", "secondary", "tertiary",
    "unclassified", "residential", "service", "living_street", "track",
}
_MODERN_POWER_TYPES = {"tower", "pole", "substation", "plant", "generator", "transformer"}
_MODERN_MAN_MADE = {"water_tank", "reservoir_covered", "tower", "mast", "works", "silo", "bunker_silo"}
_MODERN_LANDUSE = {"industrial", "commercial", "residential", "quarry", "construction"}


def _get_rss_gb() -> float:
    return psutil.Process(os.getpid()).memory_info().rss / (1024.0 ** 3)


def verify_cache_manifest(cache_dir: Path) -> dict[str, Any]:
    """Verify every file listed in data/cache/MANIFEST.sha256."""
    manifest_path = cache_dir / "MANIFEST.sha256"
    if not manifest_path.exists():
        return {"pass": False, "error": f"Missing {manifest_path}", "checked": 0, "mismatches": []}

    checked = 0
    mismatches: list[str] = []
    missing: list[str] = []

    with open(manifest_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split(None, 1)
            if len(parts) != 2:
                continue
            expected_hex, rel_path = parts[0].strip(), parts[1].strip()
            target = cache_dir / rel_path
            if not target.exists():
                missing.append(rel_path)
                continue
            h = hashlib.sha256()
            with open(target, "rb") as tf:
                while chunk := tf.read(1024 * 1024):
                    h.update(chunk)
            checked += 1
            if h.hexdigest() != expected_hex:
                mismatches.append(rel_path)

    return {
        "pass": (checked > 0 and not mismatches and not missing),
        "checked": checked,
        "missing": missing,
        "mismatches": mismatches,
    }


def _audit_bin_pack(pack_path: Path, cand: dict[str, Any]) -> dict[str, Any]:
    """Audit a single PLMP v1 binary pack against CONTRACT.md §4."""
    if not pack_path.exists():
        return {"candidate_id": cand["candidate_id"], "pass": False, "error": f"Missing pack {pack_path}"}

    file_size = pack_path.stat().st_size
    if file_size < 64:
        return {"candidate_id": cand["candidate_id"], "pass": False, "error": "File < 64 bytes"}

    with open(pack_path, "rb") as f:
        hdr = f.read(64)
        magic, version, nx, ny, x0, y0, dx, n_layers, n_pts, z_min, z_max, reserved = struct.unpack(
            "<4sIIIddfIIff12s", hdr
        )
        errors = []
        if magic != b"PLMP":
            errors.append(f"bad magic {magic!r}")
        if version != 1:
            errors.append(f"bad version {version}")
        if nx == 0 or ny == 0:
            errors.append(f"invalid dims {nx}x{ny}")
        if abs(dx - 0.5) > 1e-5:
            errors.append(f"unexpected dx={dx}")
        if n_layers != 10:
            errors.append(f"expected n_layers=10, got {n_layers}")
        if n_pts > 150000:
            errors.append(f"n_canopy_pts={n_pts} > 150000")
        if reserved != b"\x00" * 12:
            errors.append("non-zero reserved bytes")

        expected_size = 64 + n_layers * nx * ny * 4 + n_pts * 16
        if file_size != expected_size:
            errors.append(f"size mismatch: actual={file_size}, expected={expected_size}")
            return {"candidate_id": cand["candidate_id"], "pass": False, "errors": errors}

        grid_data = np.fromfile(f, dtype="<f4", count=n_layers * nx * ny).reshape((n_layers, ny, nx))
        pts_data = np.fromfile(f, dtype="<f4", count=n_pts * 4).reshape((n_pts, 4))

    if not np.all(np.isfinite(grid_data)):
        errors.append("non-finite values in planar grid layers")
    if n_pts > 0 and not np.all(np.isfinite(pts_data)):
        errors.append("non-finite values in canopy point cloud")

    cx, cy = float(cand["x_6676"]), float(cand["y_6676"])
    if not (x0 <= cx <= x0 + nx * dx and y0 <= cy <= y0 + ny * dx):
        errors.append(f"centroid ({cx}, {cy}) outside pack [{x0}, {x0+nx*dx}] x [{y0}, {y0+ny*dx}]")

    z_gnd = grid_data[0]
    if abs(float(np.min(z_gnd)) - z_min) > 1e-2 or abs(float(np.max(z_gnd)) - z_max) > 1e-2:
        errors.append(f"header z_min/z_max ({z_min:.3f}, {z_max:.3f}) != grid ({np.min(z_gnd):.3f}, {np.max(z_gnd):.3f})")

    svf = grid_data[6]
    if float(np.min(svf)) < -1e-4 or float(np.max(svf)) > 1.0 + 1e-4:
        errors.append(f"svf out of [0,1]: [{np.min(svf):.4f}, {np.max(svf):.4f}]")

    flow_v = grid_data[9]
    if float(np.min(flow_v)) < -1e-4 or float(np.max(flow_v)) > 1.0 + 1e-4:
        errors.append(f"flow_violation out of [0,1]: [{np.min(flow_v):.4f}, {np.max(flow_v):.4f}]")

    if n_pts > 0:
        rx, ry = pts_data[:, 0], pts_data[:, 1]
        if float(rx.min()) < -0.5 or float(rx.max()) > nx * dx + 0.5 or float(ry.min()) < -0.5 or float(ry.max()) > ny * dx + 0.5:
            errors.append("canopy rel_x/rel_y out of pack bounds")

    return {
        "candidate_id": cand["candidate_id"],
        "pass": len(errors) == 0,
        "nx": nx,
        "ny": ny,
        "n_canopy_pts": n_pts,
        "errors": errors,
    }


def _build_modern_osm_geoms(osm_path: Path) -> list[tuple[str, Any]]:
    """Build Shapely geometries (in EPSG:6676) for modern OSM infrastructure."""
    with open(osm_path, "r", encoding="utf-8") as f:
        osm = json.load(f)

    geoms: list[tuple[str, Any]] = []
    for feat in osm.get("tagged_features", []):
        tags = feat.get("tags", {})
        is_modern = False
        label = ""
        if "building" in tags:
            is_modern = True
            label = f"building={tags['building']}"
        elif tags.get("highway") in _MODERN_HIGHWAY_TYPES:
            is_modern = True
            label = f"highway={tags['highway']}"
        elif tags.get("power") in _MODERN_POWER_TYPES:
            is_modern = True
            label = f"power={tags['power']}"
        elif tags.get("man_made") in _MODERN_MAN_MADE:
            is_modern = True
            label = f"man_made={tags['man_made']}"
        elif tags.get("landuse") in _MODERN_LANDUSE:
            is_modern = True
            label = f"landuse={tags['landuse']}"

        if not is_modern:
            continue

        if feat.get("type") == "node" and "lat" in feat and "lon" in feat:
            x, y = _TO_6676.transform(feat["lon"], feat["lat"])
            geoms.append((f"node/{feat['id']}:{label}", Point(x, y)))
        elif feat.get("type") == "way" and feat.get("coords"):
            pts = [_TO_6676.transform(lon, lat) for lon, lat in feat["coords"]]
            if len(pts) >= 2:
                if len(pts) >= 4 and pts[0] == pts[-1] and ("building" in tags or "landuse" in tags):
                    geoms.append((f"way/{feat['id']}:{label}", Polygon(pts)))
                else:
                    geoms.append((f"way/{feat['id']}:{label}", LineString(pts)))
    return geoms


def _run_csf_on_patch(xyz: np.ndarray) -> np.ndarray:
    """Run independent CSF ground classification on a local cutout."""
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


def _audit_raw_laz_ground_counts(
    survivors: list[dict[str, Any]],
    cache_dir: Path,
) -> dict[str, Any]:
    """Re-read raw .laz tiles around every survivor and verify true ground point density >= 0.5 pts/m^2."""
    meta_path = cache_dir / "lidar_tiles_meta.json"
    with open(meta_path, "r", encoding="utf-8") as f:
        tiles_meta = json.load(f)

    # Group survivors by overlapping tiles so each LAZ file is read at most once
    tile_to_cands: dict[str, list[dict[str, Any]]] = {}
    for c in survivors:
        cx, cy = float(c["x_6676"]), float(c["y_6676"])
        r_eval = max(4.0, math.sqrt(max(float(c.get("area_m2", 25.0)), 16.0) / math.pi))
        pad = max(r_eval, 15.0)
        for tm in tiles_meta:
            x_min, y_min, _ = tm["mins"]
            x_max, y_max, _ = tm["maxs"]
            if (cx + pad >= x_min) and (cx - pad <= x_max) and (cy + pad >= y_min) and (cy - pad <= y_max):
                tile_to_cands.setdefault(tm["tile_id"], []).append(c)

    # Accumulate raw points within 15m square (for local CSF) and within feature radius (for raw count)
    cand_points: dict[str, list[tuple[np.ndarray, np.ndarray]]] = {c["candidate_id"]: [] for c in survivors}

    for tile_id, cands in tile_to_cands.items():
        laz_path = cache_dir / "lidar" / f"{tile_id}.laz"
        las = laspy.read(str(laz_path))
        x = np.asarray(las.x, dtype=np.float64)
        y = np.asarray(las.y, dtype=np.float64)
        z = np.asarray(las.z, dtype=np.float64)
        cls = np.asarray(las.classification, dtype=np.uint8)
        for c in cands:
            cx, cy = float(c["x_6676"]), float(c["y_6676"])
            m = (np.abs(x - cx) <= 15.0) & (np.abs(y - cy) <= 15.0)
            if np.any(m):
                xyz = np.column_stack([x[m], y[m], z[m]])
                cand_points[c["candidate_id"]].append((xyz, cls[m]))
        del las, x, y, z, cls

    per_cand = []
    failures = []
    for c in survivors:
        cid = c["candidate_id"]
        cx, cy = float(c["x_6676"]), float(c["y_6676"])
        r_eval = max(4.0, math.sqrt(max(float(c.get("area_m2", 25.0)), 16.0) / math.pi))
        chunks = cand_points[cid]
        if not chunks:
            failures.append(cid)
            per_cand.append({"candidate_id": cid, "pass": False, "error": "no raw LAZ points found"})
            continue
        xyz = np.vstack([ch[0] for ch in chunks])
        cls = np.concatenate([ch[1] for ch in chunks])

        csf_mask = _run_csf_on_patch(xyz)
        dist2 = (xyz[:, 0] - cx) ** 2 + (xyz[:, 1] - cy) ** 2
        in_feat = dist2 <= (r_eval ** 2)
        area_eval = math.pi * (r_eval ** 2)

        raw_las2_count = int(np.sum(in_feat & (cls == 2)))
        raw_csf_count = int(np.sum(in_feat & csf_mask))
        rho_las2 = raw_las2_count / area_eval
        rho_csf = raw_csf_count / area_eval
        # Pass if raw ground return density (via CSF or LAS class 2) >= 0.5 pts/m^2
        passed = (max(rho_las2, rho_csf) >= 0.5)
        if not passed:
            failures.append(cid)
        per_cand.append({
            "candidate_id": cid,
            "claimed_mean_rho_gnd": float(c.get("mean_rho_gnd", 0.0)),
            "raw_las2_rho_gnd": rho_las2,
            "raw_csf_rho_gnd": rho_csf,
            "raw_csf_count": raw_csf_count,
            "eval_radius_m": r_eval,
            "pass": passed,
        })

    return {
        "pass": len(failures) == 0,
        "audited_count": len(survivors),
        "failed_ids": failures,
        "details": per_cand,
    }


def _audit_gpx(gpx_path: Path, survivors: list[dict[str, Any]]) -> dict[str, Any]:
    """Parse palimpsest_waypoints.gpx, validate GPX 1.1 schema & < 0.5 m coord match."""
    if not gpx_path.exists():
        return {"pass": False, "error": f"Missing {gpx_path}"}

    tree = ET.parse(str(gpx_path))
    root = tree.getroot()
    ns = "{http://www.topografix.com/GPX/1/1}"
    if root.tag != f"{ns}gpx" or root.attrib.get("version") != "1.1":
        return {"pass": False, "error": f"Invalid GPX 1.1 root: {root.tag} v={root.attrib.get('version')}"}

    wpts: dict[str, tuple[float, float]] = {}
    for wpt in root.findall(f"{ns}wpt"):
        lat = float(wpt.attrib["lat"])
        lon = float(wpt.attrib["lon"])
        name_el = wpt.find(f"{ns}name")
        if name_el is not None and name_el.text:
            wpts[name_el.text.strip()] = (lat, lon)

    missing = []
    coord_errors = []
    max_err_m = 0.0
    for c in survivors:
        cid = c["candidate_id"]
        if cid not in wpts:
            missing.append(cid)
            continue
        glat, glon = wpts[cid]
        gx, gy = _TO_6676.transform(glon, glat)
        err_m = math.hypot(gx - float(c["x_6676"]), gy - float(c["y_6676"]))
        max_err_m = max(max_err_m, err_m)
        if err_m >= 0.5:
            coord_errors.append({"candidate_id": cid, "err_m": err_m})

    return {
        "pass": (len(missing) == 0 and len(coord_errors) == 0),
        "wpt_count": len(wpts),
        "missing_survivors": missing,
        "coord_errors": coord_errors,
        "max_coord_err_m": max_err_m,
    }


def _audit_gsi_textures(survivors: list[dict[str, Any]], out_dir: Path) -> dict[str, Any]:
    """Verify survivor textures exist (ort_USA10 is None) and are non-blank via rasterio."""
    issues = []
    checked = 0
    for c in survivors:
        cid = c["candidate_id"]
        tex = c.get("textures") or {}
        if tex.get("ort_USA10") is not None:
            issues.append({"candidate_id": cid, "issue": "ort_USA10 should be null at Takatenjin"})
        for layer in ("ort_old10", "gazo1", "seamlessphoto"):
            rel = tex.get(layer)
            if not rel:
                issues.append({"candidate_id": cid, "issue": f"missing texture path for {layer}"})
                continue
            p = out_dir / rel
            if not p.exists():
                issues.append({"candidate_id": cid, "issue": f"missing file {p}"})
                continue
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                with rasterio.open(str(p)) as ds:
                    arr = ds.read()
                    checked += 1
                    if ds.width < 64 or ds.height < 64 or float(arr.std()) < 2.0:
                        issues.append({
                            "candidate_id": cid,
                            "issue": f"blank/tiny texture {layer}: shape={arr.shape}, std={float(arr.std()):.2f}",
                        })
    return {"pass": len(issues) == 0, "textures_checked": checked, "issues": issues}


def run_self_test(cache_dir: Path | None = None) -> dict[str, Any]:
    """Validate cache manifest, OSM geometry builder, and rasterio/GPX parsers without requiring data/output/."""
    if cache_dir is None:
        cache_dir = Path(__file__).resolve().parents[2] / "data" / "cache"

    manifest_res = verify_cache_manifest(cache_dir)
    assert manifest_res["pass"], f"MANIFEST.sha256 check failed: {manifest_res}"

    geoms = _build_modern_osm_geoms(cache_dir / "osm" / "osm_features.json")
    assert len(geoms) > 50, f"Too few modern OSM geometries parsed: {len(geoms)}"

    # Verify GSI cache readability on a sample tile
    sample_png = next((cache_dir / "gsi" / "ort_old10").rglob("*.png"))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with rasterio.open(str(sample_png)) as ds:
            arr = ds.read()
            assert arr.shape[1] == 256 and arr.shape[2] == 256 and float(arr.std()) > 2.0

    # Verify coordinate round-trip accuracy < 1e-4 m
    x0, y0 = -43800.0, -144400.0
    lon, lat = _TO_WGS84.transform(x0, y0)
    xr, yr = _TO_6676.transform(lon, lat)
    rt_err = math.hypot(xr - x0, yr - y0)
    assert rt_err < 1e-4

    return {
        "status": "PASS",
        "manifest_checked_files": manifest_res["checked"],
        "modern_osm_geometries": len(geoms),
        "crs_roundtrip_err_m": rt_err,
        "rss_gb": _get_rss_gb(),
    }


def run_tier3_basin_audit(
    cache_dir: str | Path = "data/cache",
    out_dir: str | Path = "data/output",
) -> dict[str, Any]:
    """Run complete Tier-3 Real-Basin Adversarial Audit on data/output/."""
    cache_dir = Path(cache_dir)
    out_dir = Path(out_dir)

    manifest_res = verify_cache_manifest(cache_dir)

    cand_path = out_dir / "candidates.json"
    if not cand_path.exists():
        return {
            "oracle": "tier3_basin_audit",
            "status": "FAIL",
            "error": f"Missing {cand_path}",
            "manifest": manifest_res,
        }

    with open(cand_path, "r", encoding="utf-8") as f:
        dossier = json.load(f)

    all_cands = dossier.get("candidates", [])
    survivors = [c for c in all_cands if c.get("status") == "survivor"]

    # 1. Binary pack audit for all candidates with pack_file
    pack_results = []
    for c in all_cands:
        pf = c.get("pack_file")
        if pf:
            pack_results.append(_audit_bin_pack(out_dir / pf, c))
        elif c.get("status") == "survivor":
            pack_results.append({"candidate_id": c["candidate_id"], "pass": False, "error": "survivor missing pack_file"})
    pack_pass = len(survivors) > 0 and all(r["pass"] for r in pack_results)

    # 2. Raw LAZ ground-point count audit on all survivors
    raw_laz_res = _audit_raw_laz_ground_counts(survivors, cache_dir) if survivors else {"pass": False, "error": "no survivors"}

    # 3. OSM modern infrastructure audit (15 m buffer on Class A & Class B)
    osm_geoms = _build_modern_osm_geoms(cache_dir / "osm" / "osm_features.json")
    osm_violations = []
    for c in survivors:
        if c.get("temporal_class") not in ("Class A", "Class B"):
            continue
        pt = Point(float(c["x_6676"]), float(c["y_6676"]))
        for label, g in osm_geoms:
            d = float(pt.distance(g))
            if d < 15.0:
                osm_violations.append({
                    "candidate_id": c["candidate_id"],
                    "temporal_class": c.get("temporal_class"),
                    "osm_feature": label,
                    "distance_m": d,
                })
    osm_pass = (len(osm_violations) == 0)

    # 4. GSI texture audit
    gsi_res = _audit_gsi_textures(survivors, out_dir) if survivors else {"pass": False, "error": "no survivors"}

    # 5. GPX audit
    gpx_res = _audit_gpx(out_dir / "palimpsest_waypoints.gpx", survivors)

    # 6. Memory RSS audit
    peak_rss_gb = _get_rss_gb()
    pipeline_rss = dossier.get("peak_rss_gb")
    mem_pass = (peak_rss_gb < 4.0) and (pipeline_rss is None or float(pipeline_rss) < 4.0)

    overall_pass = (
        manifest_res["pass"]
        and pack_pass
        and raw_laz_res["pass"]
        and osm_pass
        and gsi_res["pass"]
        and gpx_res["pass"]
        and mem_pass
    )

    return {
        "oracle": "tier3_basin_audit",
        "status": "PASS" if overall_pass else "FAIL",
        "survivor_count": len(survivors),
        "manifest": manifest_res,
        "binary_packs": {
            "pass": pack_pass,
            "checked": len(pack_results),
            "failures": [r for r in pack_results if not r["pass"]],
        },
        "raw_laz_ground_audit": raw_laz_res,
        "osm_modern_infrastructure_audit": {
            "pass": osm_pass,
            "violations_within_15m": osm_violations,
        },
        "gsi_textures_audit": gsi_res,
        "gpx_audit": gpx_res,
        "memory_audit": {
            "pass": mem_pass,
            "auditor_rss_gb": peak_rss_gb,
            "pipeline_reported_rss_gb": pipeline_rss,
        },
    }
