"""Exports for PALIMPSEST: PLMP v1 binary packs, cropped GSI aerial textures, JSON, and GPX 1.1."""

from __future__ import annotations

import json
import math
import struct
import warnings
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.errors import NotGeoreferencedWarning

from palimpsest.detector import CandidateRecord, DetectionResult

_HEADER_FMT = "<4sIIIddfIIff12s"
_HEADER_SIZE = 64
assert struct.calcsize(_HEADER_FMT) == _HEADER_SIZE

_LAYER_NAMES = (
    "z_gnd",
    "chm",
    "rho_gnd",
    "rrim_r",
    "rrim_g",
    "rrim_b",
    "svf",
    "lrm",
    "openness_diff",
    "flow_violation",
)


def write_binary_pack(
    out_path: str | Path,
    x0: float,
    y0: float,
    dx: float,
    layers: dict[str, np.ndarray],
    canopy_pts: np.ndarray,
) -> Path:
    """Write a PLMP v1 little-endian binary tile pack matching CONTRACT.md §4."""
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    z_gnd = np.ascontiguousarray(layers["z_gnd"], dtype=np.float32)
    ny, nx = z_gnd.shape
    z_min = float(np.nanmin(z_gnd)) if z_gnd.size else 0.0
    z_max = float(np.nanmax(z_gnd)) if z_gnd.size else 0.0

    pts = np.ascontiguousarray(canopy_pts, dtype=np.float32)
    if pts.ndim != 2 or pts.shape[1] != 4:
        raise ValueError(f"canopy_pts must have shape (M, 4), got {pts.shape}")
    n_pts = int(pts.shape[0])

    header = struct.pack(
        _HEADER_FMT,
        b"PLMP",
        1,
        int(nx),
        int(ny),
        float(x0),
        float(y0),
        float(dx),
        len(_LAYER_NAMES),
        n_pts,
        z_min,
        z_max,
        b"\x00" * 12,
    )

    with open(path, "wb") as fh:
        fh.write(header)
        for name in _LAYER_NAMES:
            arr = np.ascontiguousarray(layers[name], dtype="<f4")
            if arr.shape != (ny, nx):
                raise ValueError(f"Layer '{name}' shape {arr.shape} != {(ny, nx)}")
            fh.write(arr.tobytes(order="C"))
        if n_pts > 0:
            fh.write(pts.astype("<f4", copy=False).tobytes(order="C"))

    return path


def read_binary_pack(pack_path: str | Path) -> dict[str, Any]:
    """Read a PLMP v1 binary pack back for verification and inspection."""
    path = Path(pack_path)
    with open(path, "rb") as fh:
        raw_hdr = fh.read(_HEADER_SIZE)
        if len(raw_hdr) != _HEADER_SIZE:
            raise ValueError(f"Truncated PLMP header in {path}")
        (
            magic,
            version,
            nx,
            ny,
            x0,
            y0,
            dx,
            n_layers,
            n_canopy_pts,
            z_min,
            z_max,
            _reserved,
        ) = struct.unpack(_HEADER_FMT, raw_hdr)
        if magic != b"PLMP":
            raise ValueError(f"Invalid magic {magic!r} in {path}")
        if version != 1:
            raise ValueError(f"Unsupported PLMP version {version}")
        if n_layers != len(_LAYER_NAMES):
            raise ValueError(f"Unexpected n_layers={n_layers}")

        plane_count = nx * ny
        planes_bytes = n_layers * plane_count * 4
        planes_raw = np.frombuffer(fh.read(planes_bytes), dtype="<f4")
        if planes_raw.size != n_layers * plane_count:
            raise ValueError(f"Truncated layer payload in {path}")
        planes_raw = planes_raw.reshape((n_layers, ny, nx))
        layers = {name: planes_raw[i].copy() for i, name in enumerate(_LAYER_NAMES)}

        pts_raw = np.frombuffer(fh.read(n_canopy_pts * 4 * 4), dtype="<f4")
        if pts_raw.size != n_canopy_pts * 4:
            raise ValueError(f"Truncated canopy point cloud in {path}")
        canopy_pts = pts_raw.reshape((n_canopy_pts, 4)).copy()

    return {
        "version": int(version),
        "nx": int(nx),
        "ny": int(ny),
        "x0": float(x0),
        "y0": float(y0),
        "dx": float(dx),
        "n_layers": int(n_layers),
        "n_canopy_pts": int(n_canopy_pts),
        "z_min": float(z_min),
        "z_max": float(z_max),
        "layers": layers,
        "canopy_pts": canopy_pts,
    }


def _latlon_to_tile_px(lat: np.ndarray, lon: np.ndarray, zoom: int) -> tuple[np.ndarray, np.ndarray]:
    n = 2.0 ** zoom
    lat_rad = np.radians(np.clip(lat, -85.05112878, 85.05112878))
    gx = (lon + 180.0) / 360.0 * n * 256.0
    gy = (1.0 - np.arcsinh(np.tan(lat_rad)) / math.pi) / 2.0 * n * 256.0
    return gx, gy


def _sample_gsi_layer_grid(
    gsi_dir: Path,
    layer: str,
    ext: str,
    gx: np.ndarray,
    gy: np.ndarray,
    zoom: int = 17,
) -> np.ndarray | None:
    """Sample a cached XYZ tile pyramid onto global Web Mercator pixel grid (gx, gy)."""
    layer_dir = gsi_dir / layer / str(zoom)
    if not layer_dir.is_dir():
        return None

    tx = np.floor(gx / 256.0).astype(np.int32)
    ty = np.floor(gy / 256.0).astype(np.int32)
    tx_min, tx_max = int(tx.min()), int(tx.max())
    ty_min, ty_max = int(ty.min()), int(ty.max())

    # Assemble mosaic covering needed tiles
    cols_t = tx_max - tx_min + 1
    rows_t = ty_max - ty_min + 1
    mosaic = np.zeros((rows_t * 256, cols_t * 256, 3), dtype=np.uint8)
    found_any = False

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", NotGeoreferencedWarning)
        for ix in range(tx_min, tx_max + 1):
            for iy in range(ty_min, ty_max + 1):
                tile_path = layer_dir / str(ix) / f"{iy}.{ext}"
                if not tile_path.is_file():
                    continue
                with rasterio.open(tile_path) as src:
                    arr = src.read()  # (C, H, W)
                if arr.shape[0] == 1:
                    rgb = np.repeat(arr[0:1], 3, axis=0)
                else:
                    rgb = arr[:3]
                rgb_hwc = np.moveaxis(rgb, 0, -1).astype(np.uint8, copy=False)
                oy = (iy - ty_min) * 256
                ox = (ix - tx_min) * 256
                h_t, w_t = rgb_hwc.shape[:2]
                mosaic[oy:oy + h_t, ox:ox + w_t] = rgb_hwc
                found_any = True

    if not found_any:
        return None

    lx = np.clip(gx - tx_min * 256.0, 0.0, mosaic.shape[1] - 1.001)
    ly = np.clip(gy - ty_min * 256.0, 0.0, mosaic.shape[0] - 1.001)
    x0 = np.floor(lx).astype(np.int32)
    y0 = np.floor(ly).astype(np.int32)
    fx = (lx - x0)[..., None].astype(np.float32)
    fy = (ly - y0)[..., None].astype(np.float32)

    out = (
        (1.0 - fy) * ((1.0 - fx) * mosaic[y0, x0] + fx * mosaic[y0, x0 + 1])
        + fy * ((1.0 - fx) * mosaic[y0 + 1, x0] + fx * mosaic[y0 + 1, x0 + 1])
    )
    return np.clip(np.rint(out), 0, 255).astype(np.uint8)


def crop_gsi_textures(
    cache_dir: str | Path,
    out_dir: str | Path,
    candidate_id: str,
    x0_cut: float,
    y0_cut: float,
    size_m: float = 200.0,
    tex_px: int = 256,
) -> dict[str, str | None]:
    """Crop North-up GSI historical aerial textures for a 200m x 200m cutout."""
    gsi_dir = Path(cache_dir) / "gsi"
    out_root = Path(out_dir)
    tex_dir = out_root / "packs" / "textures" / candidate_id
    tex_dir.mkdir(parents=True, exist_ok=True)

    to_4326 = Transformer.from_crs("EPSG:6676", "EPSG:4326", always_xy=True)

    # North-up image grid: row 0 = North (y0 + size_m), col 0 = West (x0)
    xs = x0_cut + (np.arange(tex_px, dtype=np.float64) + 0.5) / tex_px * size_m
    ys = y0_cut + size_m - (np.arange(tex_px, dtype=np.float64) + 0.5) / tex_px * size_m
    xg, yg = np.meshgrid(xs, ys)
    lons, lats = to_4326.transform(xg, yg)
    gx, gy = _latlon_to_tile_px(lats, lons, zoom=17)

    textures: dict[str, str | None] = {"ort_USA10": None}
    layer_specs = [
        ("ort_old10", "png", "PNG"),
        ("gazo1", "jpg", "JPEG"),
        ("seamlessphoto", "jpg", "JPEG"),
    ]

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", NotGeoreferencedWarning)
        for layer, ext, driver in layer_specs:
            rgb = _sample_gsi_layer_grid(gsi_dir, layer, ext, gx, gy, zoom=17)
            if rgb is None:
                textures[layer] = None
                continue
            out_file = tex_dir / f"{layer}.{ext}"
            chw = np.moveaxis(rgb, -1, 0)
            with rasterio.open(
                out_file,
                "w",
                driver=driver,
                width=tex_px,
                height=tex_px,
                count=3,
                dtype="uint8",
            ) as dst:
                dst.write(chw)
            textures[layer] = f"packs/textures/{candidate_id}/{layer}.{ext}"

    return textures


def build_gsi_sampler(cache_dir: str | Path) -> dict[str, Any]:
    """Return a lightweight callable sampler for historical aerial openness classification."""
    gsi_dir = Path(cache_dir) / "gsi"
    if not gsi_dir.is_dir():
        return {}

    def _sample_fn(lat: float, lon: float) -> dict[str, bool]:
        gx_c, gy_c = _latlon_to_tile_px(np.array([lat]), np.array([lon]), zoom=17)
        offs = np.arange(-12, 13, 4, dtype=np.float64)
        ox, oy = np.meshgrid(gx_c[0] + offs, gy_c[0] + offs)

        res = {"ort_old10_open": False, "gazo1_open": False}
        old_rgb = _sample_gsi_layer_grid(gsi_dir, "ort_old10", "png", ox, oy, zoom=17)
        if old_rgb is not None:
            luma = float(np.mean(old_rgb))
            p75 = float(np.percentile(old_rgb, 75))
            res["ort_old10_open"] = (luma > 135.0) or (p75 > 165.0)

        gazo_rgb = _sample_gsi_layer_grid(gsi_dir, "gazo1", "jpg", ox, oy, zoom=17)
        if gazo_rgb is not None:
            r = gazo_rgb[..., 0].astype(np.float32)
            g = gazo_rgb[..., 1].astype(np.float32)
            b = gazo_rgb[..., 2].astype(np.float32)
            luma = float(np.mean(0.299 * r + 0.587 * g + 0.114 * b))
            green_ex = float(np.mean(2.0 * g - r - b))
            res["gazo1_open"] = (luma > 130.0) and (green_ex < 12.0)

        return res

    return {"sample_fn": _sample_fn}


def write_candidates_json(
    out_path: str | Path,
    detection: DetectionResult,
    study_zone: dict[str, Any],
    fdr_q: float = 0.05,
    peak_rss_gb: float | None = None,
) -> Path:
    """Write data/output/candidates.json conforming strictly to CONTRACT.md §5."""
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "schema_version": "1.0",
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "study_zone": {
            "name": study_zone.get("name", "Takatenjin West Ridge / Ryogonjisan (高天神城西尾根・楞厳地山)"),
            "epsg": int(study_zone.get("epsg", 6676)),
            "bounds_epsg6676": study_zone.get("bounds_epsg6676", [-44800.0, -145500.0, -42800.0, -143400.0]),
            "bounds_wgs84": study_zone.get("bounds_wgs84", [138.01094, 34.68745, 138.032879, 34.706467]),
            "gsi_layers_available": study_zone.get("gsi_layers_available", ["ort_old10", "gazo1", "seamlessphoto"]),
            "gsi_attribution": study_zone.get(
                "gsi_attribution",
                "出典：国土地理院 (Geospatial Information Authority of Japan)",
            ),
        },
        "funnel": detection.funnel,
        "fdr_q": float(fdr_q),
        "fdr_p_cutoff": float(detection.fdr_threshold),
        "candidates": [
            {
                "candidate_id": c.candidate_id,
                "morphology": c.morphology,
                "status": c.status,
                "temporal_class": c.temporal_class,
                "rejection_reason": c.rejection_reason,
                "x_6676": c.x_6676,
                "y_6676": c.y_6676,
                "lat": c.lat,
                "lon": c.lon,
                "area_m2": c.area_m2,
                "wall_height_m": c.wall_height_m,
                "scarp_slope_deg": c.scarp_slope_deg,
                "local_relief_m": c.local_relief_m,
                "mean_rho_gnd": c.mean_rho_gnd,
                "min_rho_gnd": c.min_rho_gnd,
                "upslope_area_m2": c.upslope_area_m2,
                "drainage_violation": c.drainage_violation,
                "p_value": c.p_value,
                "q_value": c.q_value,
                "confidence_score": c.confidence_score,
                "osm_match": c.osm_match,
                "historical_notes": c.historical_notes,
                "pack_file": c.pack_file,
                "textures": c.textures,
            }
            for c in detection.candidates
        ],
    }

    if peak_rss_gb is not None:
        payload["peak_rss_gb"] = peak_rss_gb

    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)

    return path


def write_waypoints_gpx(
    out_path: str | Path,
    survivors: list[CandidateRecord],
    dtm: np.ndarray,
    x0: float,
    y0: float,
    dx: float,
) -> Path:
    """Write standard GPX 1.1 waypoints for all surviving candidates matching CONTRACT.md §6."""
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    ny, nx = dtm.shape
    sym_map = {
        "Class A": "Flag, Red",
        "Class B": "Flag, Blue",
        "Class C": "Flag, Green",
    }

    gpx = ET.Element(
        "gpx",
        {
            "version": "1.1",
            "creator": "PALIMPSEST",
            "xmlns": "http://www.topografix.com/GPX/1/1",
        },
    )
    meta = ET.SubElement(gpx, "metadata")
    ET.SubElement(meta, "name").text = "PALIMPSEST Archaeological Prospection Waypoints"
    ET.SubElement(meta, "time").text = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    for rec in survivors:
        col = int(np.clip(round((rec.x_6676 - x0) / dx - 0.5), 0, nx - 1))
        row = int(np.clip(round((rec.y_6676 - y0) / dx - 0.5), 0, ny - 1))
        ele_val = float(dtm[row, col])

        wpt = ET.SubElement(
            gpx,
            "wpt",
            {
                "lat": f"{rec.lat:.7f}",
                "lon": f"{rec.lon:.7f}",
            },
        )
        ET.SubElement(wpt, "ele").text = f"{ele_val:.2f}"
        ET.SubElement(wpt, "name").text = rec.candidate_id
        ET.SubElement(wpt, "cmt").text = (
            f"[{rec.temporal_class}] {rec.morphology} | "
            f"wall={rec.wall_height_m:.1f}m scarp={rec.scarp_slope_deg:.1f}° rho={rec.mean_rho_gnd:.2f}/m2"
        )
        ET.SubElement(wpt, "sym").text = sym_map.get(rec.temporal_class, "Flag, Red")
        ET.SubElement(wpt, "type").text = rec.temporal_class

    ET.indent(gpx, space="  ")
    tree = ET.ElementTree(gpx)
    tree.write(path, encoding="utf-8", xml_declaration=True)
    return path
