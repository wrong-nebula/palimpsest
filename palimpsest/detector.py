"""3-Morphology archaeological detector, provenance gate, falsifiers, and Time-Machine Diff."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
from pyproj import Transformer
from scipy.ndimage import distance_transform_edt
from shapely.geometry import LineString, Point, Polygon, shape
from shapely.strtree import STRtree

from palimpsest.derivatives import (
    DerivativeBundle,
    benjamini_hochberg_fdr,
    compute_bh_qvalues,
    compute_dinf_flow,
    compute_drainage_violation,
    compute_lrm,
)
from palimpsest.profiles import scan_profiles


@dataclass
class CandidateRecord:
    candidate_id: str                # e.g. "PLMP-0001"
    morphology: str                  # "terrace" | "mound_pit" | "horikiri"
    status: str                      # "survivor" | "rejected"
    temporal_class: str              # "Class A" | "Class B" | "Class C" | "Rejected"
    rejection_reason: str | None     # None if survivor; else e.g. "low_rho_gnd", "forestry_switchback", "osm_modern", "fdr_rejected", "natural_thalweg"
    x_6676: float                    # centroid X (EPSG:6676)
    y_6676: float                    # centroid Y (EPSG:6676)
    lat: float                       # WGS84 latitude
    lon: float                       # WGS84 longitude
    area_m2: float
    wall_height_m: float
    scarp_slope_deg: float
    local_relief_m: float
    mean_rho_gnd: float              # pts/m^2 inside feature
    min_rho_gnd: float               # pts/m^2 minimum inside feature
    upslope_area_m2: float
    drainage_violation: float
    p_value: float
    q_value: float
    confidence_score: float          # [0, 1]
    osm_match: str | None
    historical_notes: str
    pack_file: str | None            # relative path e.g. "packs/PLMP-0001.bin"
    textures: dict[str, str | None]  # {"ort_USA10": None, "ort_old10": "...", "gazo1": "...", "seamlessphoto": "..."}


@dataclass
class DetectionResult:
    candidates: list[CandidateRecord]
    survivors: list[CandidateRecord]
    funnel: dict[str, int]
    fdr_threshold: float


def _get_deriv(derivatives: DerivativeBundle | dict[str, np.ndarray], key: str) -> np.ndarray | None:
    if isinstance(derivatives, dict):
        if key in derivatives:
            return derivatives[key]
        if key == "I_10" and "openness_diff" in derivatives:
            return derivatives["openness_diff"]
        return None
    return getattr(derivatives, key, None)


class _OSMIndex:
    def __init__(self, osm_vectors: dict | list | None, to_6676: Transformer) -> None:
        self.modern_geoms: list[Any] = []
        self.modern_labels: list[str] = []
        self.track_geoms: list[Any] = []
        self.track_labels: list[str] = []
        self.water_geoms: list[Any] = []
        self.historic_geoms: list[Any] = []
        self.historic_labels: list[str] = []

        if osm_vectors:
            self._ingest(osm_vectors, to_6676)

        self.modern_tree = STRtree(self.modern_geoms) if self.modern_geoms else None
        self.track_tree = STRtree(self.track_geoms) if self.track_geoms else None
        self.water_tree = STRtree(self.water_geoms) if self.water_geoms else None
        self.historic_tree = STRtree(self.historic_geoms) if self.historic_geoms else None

    def _to_xy(self, lon: float, lat: float, to_6676: Transformer) -> tuple[float, float]:
        x, y = to_6676.transform(lon, lat)
        return float(x), float(y)

    def _classify_and_add(self, geom: Any, tags: dict[str, Any], label_str: str) -> None:
        if geom is None or geom.is_empty:
            return
        name = str(tags.get("name", ""))
        historic = any(key in tags for key in ("historic", "castle_type", "memorial"))
        if historic or any(tok in name for tok in ("高天神", "城跡", "砦", "曲輪")):
            self.historic_geoms.append(geom)
            self.historic_labels.append(name or str(tags.get("historic", label_str)))
        # A feature can carry both a historic tag and a modern road/building tag.
        power = str(tags.get("power", ""))
        man_made = str(tags.get("man_made", ""))
        landuse = str(tags.get("landuse", ""))
        highway = str(tags.get("highway", ""))
        waterway = str(tags.get("waterway", ""))
        amenity = str(tags.get("amenity", ""))

        is_modern = (
            "building" in tags
            or power in ("tower", "pole", "substation", "line", "portal", "generator", "plant", "transformer")
            or man_made in ("water_tower", "storage_tank", "tower", "mast", "reservoir_covered", "works", "water_tank", "silo", "bunker_silo")
            or landuse in ("industrial", "commercial", "quarry", "residential", "retail", "construction", "farmyard",
                          "farmland", "orchard", "vineyard", "plant_nursery", "greenhouse_horticulture")
            or highway in ("motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential", "service", "living_street")
            or "railway" in tags
            or (amenity != "" and amenity not in ("grave_yard", "bench"))
        )
        if is_modern:
            tag_desc = (
                f"power={power}" if power
                else f"building={tags.get('building')}" if "building" in tags
                else f"highway={highway}" if highway
                else f"man_made={man_made}" if man_made
                else f"landuse={landuse}" if landuse
                else label_str
            )
            self.modern_geoms.append(geom)
            self.modern_labels.append(tag_desc)
            return

        if highway in ("track", "path", "footway", "bridleway", "cycleway", "steps", "road"):
            self.track_geoms.append(geom)
            self.track_labels.append(f"highway={highway}")
            return

        if waterway in ("river", "stream", "canal", "drain", "ditch"):
            self.water_geoms.append(geom)

    def _ingest(self, osm_vectors: dict | list, to_6676: Transformer) -> None:
        features: list[dict] = []
        nodes_lookup: dict[str, dict] = {}
        if isinstance(osm_vectors, dict):
            if "nodes" in osm_vectors and isinstance(osm_vectors["nodes"], dict):
                nodes_lookup = osm_vectors["nodes"]
            if "tagged_features" in osm_vectors:
                features.extend(osm_vectors["tagged_features"])
            if "features" in osm_vectors:
                features.extend(osm_vectors["features"])
            if "osm_historic_and_peak_features" in osm_vectors:
                features.extend(osm_vectors["osm_historic_and_peak_features"])
            if not features and "ways" in osm_vectors and isinstance(osm_vectors["ways"], dict):
                for wid, w in osm_vectors["ways"].items():
                    if w.get("tags"):
                        features.append({"type": "way", "id": wid, **w})
        elif isinstance(osm_vectors, list):
            features = osm_vectors

        for feat in features:
            if not isinstance(feat, dict):
                continue
            tags = feat.get("tags") or feat.get("properties") or {}
            if not tags and any(k in feat for k in ("power", "building", "highway", "historic", "man_made", "waterway")):
                tags = feat
            if not tags:
                continue

            geom = None
            if "geometry" in feat and isinstance(feat["geometry"], dict):
                g_raw = shape(feat["geometry"])
                if g_raw.geom_type == "Point":
                    x, y = self._to_xy(g_raw.x, g_raw.y, to_6676)
                    geom = Point(x, y)
                elif g_raw.geom_type == "LineString":
                    pts = [self._to_xy(c[0], c[1], to_6676) for c in g_raw.coords]
                    if len(pts) >= 2:
                        geom = LineString(pts)
                elif g_raw.geom_type == "Polygon":
                    pts = [self._to_xy(c[0], c[1], to_6676) for c in g_raw.exterior.coords]
                    if len(pts) >= 3:
                        geom = Polygon(pts)
            elif "x_6676" in feat and "y_6676" in feat:
                geom = Point(float(feat["x_6676"]), float(feat["y_6676"]))
            elif "x" in feat and "y" in feat:
                geom = Point(float(feat["x"]), float(feat["y"]))
            elif "lat" in feat and "lon" in feat:
                x, y = self._to_xy(float(feat["lon"]), float(feat["lat"]), to_6676)
                geom = Point(x, y)
            elif "coords" in feat and isinstance(feat["coords"], list) and len(feat["coords"]) >= 2:
                pts = [self._to_xy(float(c[0]), float(c[1]), to_6676) for c in feat["coords"]]
                if len(pts) >= 4 and pts[0] == pts[-1] and ("building" in tags or "landuse" in tags):
                    geom = Polygon(pts)
                else:
                    geom = LineString(pts)
            elif "nodes" in feat and nodes_lookup:
                pts = []
                for nid in feat["nodes"]:
                    nd = nodes_lookup.get(str(nid))
                    if nd and "lat" in nd and "lon" in nd:
                        pts.append(self._to_xy(float(nd["lon"]), float(nd["lat"]), to_6676))
                if len(pts) >= 2:
                    if len(pts) >= 4 and pts[0] == pts[-1] and ("building" in tags or "landuse" in tags):
                        geom = Polygon(pts)
                    else:
                        geom = LineString(pts)

            lbl = f"{feat.get('type', 'osm')}/{feat.get('id', '')}"
            self._classify_and_add(geom, tags, lbl)

    def check_modern(self, pt: Point, buf_m: float = 15.0) -> str | None:
        if self.modern_tree is None:
            return None
        idxs = self.modern_tree.query(pt.buffer(buf_m))
        for idx in idxs:
            if self.modern_geoms[idx].distance(pt) <= buf_m:
                return self.modern_labels[idx]
        return None

    def check_track(self, pt: Point, buf_m: float = 12.0) -> str | None:
        if self.track_tree is None:
            return None
        idxs = self.track_tree.query(pt.buffer(buf_m))
        for idx in idxs:
            if self.track_geoms[idx].distance(pt) <= buf_m:
                return self.track_labels[idx]
        return None

    def check_water(self, pt: Point, buf_m: float = 10.0) -> bool:
        if self.water_tree is None:
            return False
        idxs = self.water_tree.query(pt.buffer(buf_m))
        for idx in idxs:
            if self.water_geoms[idx].distance(pt) <= buf_m:
                return True
        return False

    def check_historic(self, pt: Point, buf_m: float = 80.0) -> str | None:
        if self.historic_tree is None:
            return None
        idxs = self.historic_tree.query(pt.buffer(buf_m))
        for idx in idxs:
            if self.historic_geoms[idx].distance(pt) <= buf_m:
                return self.historic_labels[idx]
        return None


def _ridge_shoulders(z, support, across, along, scale, relief):
    """Check observed banks and an intact crest after removing only the local grade."""
    a, b = np.broadcast_arrays(across/scale, along/scale)
    flank = support & (np.abs(a) > 1.0) & (np.abs(a) <= 2.5) & (np.abs(b) <= 2.8)
    if np.count_nonzero(flank) < 12:
        return False
    design = np.column_stack([np.ones(flank.sum()), a[flank], b[flank]])
    offset, tilt_a, tilt_b = np.linalg.lstsq(design, z[flank], rcond=None)[0]
    # An incision running down the local fall line is consistent with a
    # drainage channel. Use the observed banks outside the trench to estimate
    # that direction. On nearly level crests the aspect is indeterminate.
    if abs(tilt_b) > max(0.10 * scale, abs(tilt_a)):
        return False
    leveled = z - (offset + tilt_a*a + tilt_b*b)
    left = support & (a < -1.0) & (a > -2.4)
    right = support & (a > 1.0) & (a < 2.4)
    floor = support & (np.abs(a) < 0.6)

    def height(region):
        return np.median(leveled[region]) if np.count_nonzero(region) >= 3 else np.nan

    banks = []
    for station in (-1.25, 0., 1.25):
        strip = np.abs(b - station) < 0.6
        banks.append(np.minimum(height(left & strip), height(right & strip)) - height(floor & strip))
    if not banks[1] > 0.30*relief or np.count_nonzero(np.asarray(banks) > 0.25*relief) < 2:
        return False

    # A crest continues on at least one of the intact banks of a transverse
    # cut. Its centre stands above both ends after accounting for the grade.
    for bank in (left, right):
        crown = height(bank & (np.abs(b) < 0.7))
        ends = np.maximum(height(bank & (b > 1.6) & (b < 2.8)),
                          height(bank & (b < -1.6) & (b > -2.8)))
        if crown - ends > 0.10:
            return True
    return False


def _temporal_class(mean_chm: float, historic_match: str | None, historical_open: bool) -> tuple[str, str]:
    if historic_match is not None:
        return "Class C", f"Within the historic-anchor buffer of {historic_match}. Current CHM={mean_chm:.1f}m."
    if historical_open:
        return "Class B", f"Historical aerial brightness suggests a clearing. Current CHM={mean_chm:.1f}m."
    return "Class A", f"Canopy-covered relief (CHM={mean_chm:.1f}m). No mapped infrastructure or historical clearing signal."


def detect_candidates(
    dtm: np.ndarray,
    chm: np.ndarray,
    rho_gnd: np.ndarray,
    derivatives: DerivativeBundle | dict[str, np.ndarray],
    osm_vectors: dict | list | None = None,
    gsi_layers: dict | None = None,
    *,
    x0: float = 0.0,
    y0: float = 0.0,
    dx: float = 0.5,
    fdr_q: float = 0.05,
    min_rho_gnd: float = 0.5,
) -> DetectionResult:
    """Detect and falsify 3 anthropogenic morphologies with strict rho_gnd gating and BH-FDR."""
    dtm32 = np.asarray(dtm, dtype=np.float32)
    chm32 = np.asarray(chm, dtype=np.float32)
    rho32 = np.asarray(rho_gnd, dtype=np.float32)
    ny, nx = dtm32.shape

    slope_rad = _get_deriv(derivatives, "slope_rad")
    if slope_rad is None:
        gy, gx = np.gradient(dtm32, np.float32(dx))
        slope_rad = np.arctan(np.hypot(gx, gy)).astype(np.float32)

    min_rho_gnd = max(0.5, min_rho_gnd)
    lrm = _get_deriv(derivatives, "lrm")
    if lrm is None:
        lrm = compute_lrm(dtm32, dx=dx, radius_m=15.0)
    upslope_a = _get_deriv(derivatives, "upslope_area_m2")
    drain_viol = _get_deriv(derivatives, "drainage_violation")
    if upslope_a is None or drain_viol is None:
        flow, upslope_a, _ = compute_dinf_flow(dtm32, dx=dx)
        drain_viol = compute_drainage_violation(dtm32, flow, upslope_a, slope_rad, dx)

    to_6676 = Transformer.from_crs(4326, 6676, always_xy=True)
    to_4326 = Transformer.from_crs(6676, 4326, always_xy=True)
    osm_idx = _OSMIndex(osm_vectors, to_6676)
    n_raw_components, n_after_prov_gate, hits, family_size = scan_profiles(dtm32, rho32, dx, min_rho_gnd)
    # Keep a single hypothesis per physical feature across scales and classes.
    hits.sort(key=lambda hit: hit[5])
    dedup = []
    occupied = np.zeros((ny, nx), dtype=bool)
    for kind, row, col, scale, angle, pv, improvement, relief, grade, is_switchback in hits:
        if occupied[row, col]:
            continue
        rad = int(math.ceil(3 * scale / dx))
        rs = slice(max(0, row-rad), min(ny, row+rad+1))
        cs = slice(max(0, col-rad), min(nx, col+rad+1))
        y, x = np.ogrid[rs.start-row:rs.stop-row, cs.start-col:cs.stop-col]
        x, y = x*dx, y*dx
        distance = np.hypot(x, y)
        if kind == "horikiri":
            across = x*math.cos(angle) + y*math.sin(angle)
            along = -x*math.sin(angle) + y*math.cos(angle)
            extent = np.hypot(across, along/2.4)
        else:
            extent = distance
        support = (rho32[rs, cs] >= min_rho_gnd) & np.isfinite(dtm32[rs, cs])
        footprint = (extent <= 0.85*scale) & support
        collar = (extent > 0.7*scale) & (extent < 1.5*scale) & support
        if not footprint.any() or not collar.any():
            continue
        if np.mean(rho32[rs, cs][extent <= 0.85*scale]) < min_rho_gnd:
            continue
        # A few valid returns at a centre cannot authenticate banks assembled
        # across a contiguous TIN facet. Require independent observations on
        # each side at the native density resolution.
        aperture = distance <= 1.6*scale
        sector = ((np.arctan2(y, x) + np.pi)*(4/np.pi)).astype(int) % 8
        sectors = sector[aperture]
        total = np.bincount(sectors, minlength=8)
        observed = np.bincount(sectors, weights=support[aperture], minlength=8)
        coverage = observed / np.maximum(total, 1)
        gap_m = dx * np.max(distance_transform_edt(~support)[aperture])
        if (np.mean(support[distance <= 0.65*scale]) < 0.60
                or np.count_nonzero(coverage >= 0.50) < 6
                or np.min(coverage) < 0.15 or gap_m > max(1.5, 0.5*scale)):
            continue
        if kind == "horikiri" and not _ridge_shoulders(
            dtm32[rs, cs], support, across, along, scale, relief
        ):
            continue
        occupied[rs, cs] |= distance <= max(5., 1.4*scale)
        x_m, y_m = x0+(col+0.5)*dx, y0+(row+0.5)*dx
        lon, lat = to_4326.transform(x_m, y_m)
        up = float(np.percentile(upslope_a[rs, cs][footprint], 90))
        canopy = chm32[rs, cs]
        context = distance <= max(8., scale)
        p = dict(
            x_6676=x_m, y_6676=y_m, lon=lon, lat=lat,
            area_m2=footprint.sum()*dx*dx,
            wall_height_m=relief,
            scarp_slope_deg=float(np.rad2deg(np.percentile(slope_rad[rs, cs][collar], 95))),
            local_relief_m=float(np.max(np.abs(lrm[rs, cs][footprint]))),
            mean_rho=float(np.mean(rho32[rs, cs][footprint])),
            min_rho=float(np.min(rho32[rs, cs][footprint])),
            upslope_area_m2=up,
            drainage_violation=float(np.percentile(drain_viol[rs, cs][footprint],90)),
            mean_chm=float(np.mean(canopy[extent <= 0.85*scale])),
            context_chm=float(np.mean(canopy[context])),
        )
        dedup.append(dict(morphology=kind, props=p, p_value=pv,
                          is_switchback=is_switchback, is_natural_thalweg=up >= 600.0))

    n_after_morph = len(dedup)
    if n_after_morph == 0:
        return DetectionResult(
            candidates=[],
            survivors=[],
            funnel={
                "raw_peaks_or_cells": int(n_raw_components),
                "after_rho_gnd_gate": int(n_after_prov_gate),
                "after_morphology_filter": 0,
                "after_bh_fdr": 0,
                "after_geomorphic_falsifier": 0,
                "after_osm_historical_diff": 0,
                "survivors_total": 0,
            },
            fdr_threshold=0.0,
        )

    # --- Step 3: Benjamini-Hochberg Spatial FDR ---
    # Selecting extrema on the same surface is a search over every measured
    # centre at every scale and morphology. The unselected tests have p=1.
    # Scale the BH ranks analytically to avoid materializing millions of ones.
    p_vals = np.array([item["p_value"] for item in dedup], dtype=np.float64)
    family_ratio = max(1., family_size / len(p_vals))
    fdr_mask, fdr_cutoff = benjamini_hochberg_fdr(p_vals, q=float(fdr_q)/family_ratio)
    q_vals = np.minimum(1., compute_bh_qvalues(p_vals)*family_ratio)
    n_after_fdr = int(np.count_nonzero(fdr_mask))

    # --- Step 4: Geomorphic Falsifiers & OSM / Historical Diff ---
    n_after_geom = 0
    n_after_osm = 0
    candidates: list[CandidateRecord] = []
    survivors: list[CandidateRecord] = []

    for idx, item in enumerate(dedup):
        p = item["props"]
        pt = Point(p["x_6676"], p["y_6676"])
        qv = float(q_vals[idx])
        pv = float(p_vals[idx])

        status = "survivor"
        rejection_reason: str | None = None
        osm_match: str | None = None

        if not bool(fdr_mask[idx]):
            status = "rejected"
            rejection_reason = "fdr_rejected"
        elif item["is_switchback"]:
            status = "rejected"
            rejection_reason = "forestry_switchback"

        elif item["is_natural_thalweg"] or osm_idx.check_water(pt, buf_m=10.0):
            status = "rejected"
            rejection_reason = "natural_thalweg"
        else:
            n_after_geom += 1
            modern_hit = osm_idx.check_modern(pt, buf_m=15.0)
            track_hit = osm_idx.check_track(pt, buf_m=15.0)
            hist_hit = osm_idx.check_historic(pt, buf_m=80.0)
            if modern_hit is not None:
                status = "rejected"
                rejection_reason = "osm_modern"
                osm_match = modern_hit
            elif track_hit is not None:
                status = "rejected"
                rejection_reason = "forestry_switchback" if item["morphology"] == "terrace" else "osm_modern"
                osm_match = track_hit
            else:
                gsi_open_hist = False
                if gsi_layers and callable(gsi_layers.get("sample_fn")):
                    _st = gsi_layers["sample_fn"](p["lat"], p["lon"])
                    gsi_open_hist = bool(_st.get("ort_old10_open", False) or _st.get("gazo1_open", False))
                is_modern_clearing = hist_hit is None and (
                    p["context_chm"] < 3.0 or p["mean_chm"] < 5.0 or (gsi_open_hist and p["mean_chm"] <= 8.0)
                )
                if is_modern_clearing:
                    status = "rejected"
                    rejection_reason = "modern_open_clearing"
                else:
                    n_after_osm += 1

        if status == "survivor":
            hist_hit = osm_idx.check_historic(pt, buf_m=80.0)
            if hist_hit is not None:
                osm_match = hist_hit
            t_class, hist_notes = _temporal_class(p["mean_chm"], hist_hit, gsi_open_hist)
            conf = float(np.clip(
                0.35 * (1.0 - min(1.0, qv / max(float(fdr_q), 1e-6)))
                + 0.25 * min(1.0, p["mean_rho"] / 2.5)
                + 0.20 * min(1.0, p["local_relief_m"] / 1.5)
                + 0.20 * min(1.0, p["drainage_violation"] / 0.8),
                0.0,
                1.0,
            ))
        else:
            t_class = "Rejected"
            hist_notes = f"Falsified ({rejection_reason})" + (f" [{osm_match}]" if osm_match else "")
            if rejection_reason == "modern_open_clearing":
                hist_notes += f". Current footprint CHM={p['mean_chm']:.1f}m, surrounding CHM={p['context_chm']:.1f}m."
            conf = 0.0

        rec = CandidateRecord(
            candidate_id=f"PLMP-{idx + 1:04d}",
            morphology=item["morphology"],
            status=status,
            temporal_class=t_class,
            rejection_reason=rejection_reason,
            x_6676=round(p["x_6676"], 2),
            y_6676=round(p["y_6676"], 2),
            lat=round(p["lat"], 7),
            lon=round(p["lon"], 7),
            area_m2=round(p["area_m2"], 2),
            wall_height_m=round(p["wall_height_m"], 3),
            scarp_slope_deg=round(p["scarp_slope_deg"], 2),
            local_relief_m=round(p["local_relief_m"], 3),
            mean_rho_gnd=round(p["mean_rho"], 3),
            min_rho_gnd=round(p["min_rho"], 3),
            upslope_area_m2=round(p["upslope_area_m2"], 2),
            drainage_violation=round(p["drainage_violation"], 3),
            p_value=pv,
            q_value=qv,
            confidence_score=round(conf, 4),
            osm_match=osm_match,
            historical_notes=hist_notes,
            pack_file=None,
            textures={"ort_USA10": None, "ort_old10": None, "gazo1": None, "seamlessphoto": None},
        )
        candidates.append(rec)
        if status == "survivor":
            survivors.append(rec)

    # Sort survivors by confidence descending
    survivors.sort(key=lambda r: (-r.confidence_score, r.p_value))
    # Re-assign clean sequential IDs prioritizing top survivors first, then rejected
    ordered = survivors + [c for c in candidates if c.status != "survivor"]
    for i, rec in enumerate(ordered, start=1):
        rec.candidate_id = f"PLMP-{i:04d}"

    funnel = {
        "raw_peaks_or_cells": int(n_raw_components),
        "after_rho_gnd_gate": int(n_after_prov_gate),
        "after_morphology_filter": int(n_after_morph),
        "after_bh_fdr": int(n_after_fdr),
        "after_geomorphic_falsifier": int(n_after_geom),
        "after_osm_historical_diff": int(n_after_osm),
        "survivors_total": len(survivors),
    }

    return DetectionResult(
        candidates=ordered,
        survivors=survivors,
        funnel=funnel,
        fdr_threshold=float(fdr_cutoff),
    )
