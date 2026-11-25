"""Tier 1 Firewall Oracles for PALIMPSEST.

Tests two non-negotiable anti-hallucination & falsification firewalls:
1. Canopy-Dropout Blackout Patch Oracle (0 false detections):
   - Realistic hilly forest DTM with a 22 m x 22 m canopy-dropout blackout patch
     where rho_gnd = 0 and DTM is replaced by sharp planar Delaunay TIN facets
     (including an adversarial flat-ish facet that mimics a terrace in slope/LRM).
   - Asserts strictly 0 surviving detections overlapping the blackout zone.
2. Forestry Switchback & OSM Transmission Tower Pad Firewall (>= 95% rejection):
   - Unmapped 3.5 m wide contour-following forestry cut-and-fill switchback
     (3 legs + 2 hairpin bends, > 400 m total length) on a steep 26 deg hillslope.
   - 4 square 12 m x 12 m modern cut-and-fill transmission tower pads mapped as
     `power=tower` in `osm_vectors` (matching data/cache/osm/osm_features.json schema).
   - Asserts >= 95% of decoy features and decoy footprint area are rejected
     (surviving false positives <= 5%).
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from pyproj import Transformer
from scipy.interpolate import LinearNDInterpolator


_TO_WGS84 = Transformer.from_crs("EPSG:6676", "EPSG:4326", always_xy=True)


def generate_blackout_patch_scene(
    x0: float = -44000.0,
    y0: float = -144500.0,
    extent_m: float = 200.0,
    dx: float = 0.5,
    seed: int = 202601,
) -> dict[str, Any]:
    """Generate hilly forest DTM with a 22 m x 22 m canopy-dropout TIN blackout patch."""
    rng = np.random.default_rng(seed)
    n = int(round(extent_m / dx))
    xs = (np.arange(n, dtype=np.float64) + 0.5) * dx
    ys = (np.arange(n, dtype=np.float64) + 0.5) * dx
    X, Y = np.meshgrid(xs, ys, indexing="xy")

    # Realistic 24-deg hilly forest slope with ridge/valley undulations
    dtm = (
        110.0
        + 0.44 * X
        + 0.0008 * (X - 100.0) ** 2
        + 2.8 * np.sin(X / 32.0) * np.cos(Y / 38.0)
        + 0.04 * rng.standard_normal((n, n))
    )

    # Realistic forest ground return density: 1.5 - 3.8 pts/m^2 outside blackout
    rho_gnd = 2.4 + 0.8 * np.sin(X / 25.0) * np.cos(Y / 27.0) + 0.25 * rng.standard_normal((n, n))
    rho_gnd = np.clip(rho_gnd, 1.0, 5.0)

    # Dense forest CHM (14 - 28 m)
    chm = 18.0 + 4.0 * np.sin(X / 18.0 + 0.4) * np.cos(Y / 21.0)

    # 22 m x 22 m canopy-dropout blackout zone centered at (100, 100) m
    cx, cy, half_w = 100.0, 100.0, 11.0
    blackout_mask = (np.abs(X - cx) <= half_w) & (np.abs(Y - cy) <= half_w)

    # Set rho_gnd = 0 strictly inside blackout (with sharp dropout edge)
    rho_gnd[blackout_mask] = 0.0
    chm[blackout_mask] = 27.5  # dense canopy crown causing total ground dropout

    # Construct adversarial planar Delaunay TIN facets across sparse perimeter anchors
    # Include anchors that form an artificial flat-like triangular facet across the middle
    anchor_offsets = np.array([
        [-12.0, -12.0], [0.0, -12.5], [12.0, -12.0],
        [-12.5, 0.0], [12.5, 0.0],
        [-12.0, 12.0], [0.0, 12.5], [12.0, 12.0],
        [-11.5, -5.5], [11.5, 5.5],
    ])
    ax = cx + anchor_offsets[:, 0]
    ay = cy + anchor_offsets[:, 1]
    az = (
        110.0
        + 0.44 * ax
        + 0.0008 * (ax - 100.0) ** 2
        + 2.8 * np.sin(ax / 32.0) * np.cos(ay / 38.0)
    )
    # Perturb two anchors slightly to create crisp false terrace-like TIN breaklines
    az[3] += 2.2
    az[4] -= 2.2
    tin_interp = LinearNDInterpolator(np.column_stack([ax, ay]), az)
    tin_z = tin_interp(X[blackout_mask], Y[blackout_mask])
    valid_tin = np.isfinite(tin_z)
    dtm_blackout = dtm[blackout_mask].copy()
    dtm_blackout[valid_tin] = tin_z[valid_tin]
    dtm[blackout_mask] = dtm_blackout

    return {
        "dtm": dtm.astype(np.float32),
        "chm": chm.astype(np.float32),
        "rho_gnd": rho_gnd.astype(np.float32),
        "blackout_mask": blackout_mask,
        "blackout_bbox_6676": (x0 + cx - half_w, y0 + cy - half_w, x0 + cx + half_w, y0 + cy + half_w),
        "x0": x0,
        "y0": y0,
        "dx": dx,
    }


def _build_switchback_polyline(extent_m: float = 300.0) -> list[np.ndarray]:
    """Build 3-leg forestry switchback road with 2 hairpin bends across a steep East-sloping hill."""
    # Hillslope descends toward -X or +X: let z(x, y) = 190 - 0.48 * x (steep ~25.6 deg Eastward slope)
    # Switchback runs approximately North-South (along Y, gentle grade) with 2 sharp hairpins:
    # Leg 1: (x=90..115, y=40..255)
    # Hairpin 1: smooth arc around (125, 260)
    # Leg 2: (x=135..158, y=255..50)
    # Hairpin 2: smooth arc around (168, 45)
    # Leg 3: (x=178..200, y=50..255)
    pts = []
    # Leg 1 (S -> N)
    for t in np.linspace(0.0, 1.0, 110):
        pts.append([95.0 + 18.0 * t + 3.0 * math.sin(t * math.pi), 45.0 + 210.0 * t])
    # Hairpin 1 (turning downslope to Leg 2)
    for th in np.linspace(math.pi, 0.0, 24)[1:-1]:
        pts.append([125.0 - 12.0 * math.cos(th), 255.0 + 11.0 * math.sin(th)])
    # Leg 2 (N -> S)
    for t in np.linspace(0.0, 1.0, 110):
        pts.append([137.0 + 20.0 * t - 2.5 * math.sin(t * math.pi), 255.0 - 205.0 * t])
    # Hairpin 2 (turning downslope to Leg 3)
    for th in np.linspace(math.pi, 2.0 * math.pi, 24)[1:-1]:
        pts.append([169.0 - 12.0 * math.cos(th), 50.0 + 11.0 * math.sin(th)])
    # Leg 3 (S -> N)
    for t in np.linspace(0.0, 1.0, 110):
        pts.append([181.0 + 16.0 * t, 50.0 + 200.0 * t])
    return [np.asarray(pts, dtype=np.float64)]


def generate_firewall_decoy_scene(
    x0: float = -44200.0,
    y0: float = -144700.0,
    extent_m: float = 300.0,
    dx: float = 0.5,
    seed: int = 202602,
) -> dict[str, Any]:
    """Generate steep forested slope with:
    - Unmapped 3.5 m cut-and-fill forestry switchback road (3 legs + 2 hairpins)
    - 4 square cut-and-fill transmission tower pads mapped in OSM (`power=tower`)
    """
    rng = np.random.default_rng(seed)
    n = int(round(extent_m / dx))
    xs = (np.arange(n, dtype=np.float64) + 0.5) * dx
    ys = (np.arange(n, dtype=np.float64) + 0.5) * dx
    X, Y = np.meshgrid(xs, ys, indexing="xy")

    # Steep ~26.5 deg hillslope descending Eastward
    z_bg = 210.0 - 0.50 * X + 2.2 * np.sin(Y / 55.0) + 0.03 * rng.standard_normal((n, n))
    dtm = z_bg.copy()
    rho_gnd = np.clip(2.2 + 0.6 * np.cos(X / 30.0) + 0.2 * rng.standard_normal((n, n)), 1.0, 5.0)
    chm = 16.5 + 3.5 * np.sin(X / 25.0) * np.cos(Y / 22.0)

    # 1. Carve 3.5 m wide cut-and-fill forestry switchback road (NOT in OSM!)
    polylines = _build_switchback_polyline(extent_m)
    road_pts = polylines[0]
    # Sample densely along polyline to compute exact distance to centerline
    dense_pts = []
    for i in range(len(road_pts) - 1):
        p0, p1 = road_pts[i], road_pts[i + 1]
        seg_len = float(np.linalg.norm(p1 - p0))
        k = max(2, int(math.ceil(seg_len / 0.25)))
        for s in np.linspace(0.0, 1.0, k, endpoint=(i == len(road_pts) - 2)):
            dense_pts.append(p0 + s * (p1 - p0))
    dense_pts = np.asarray(dense_pts, dtype=np.float64)
    # Roadbed elevation at each dense point = background elevation along centerline (smoothed slightly)
    road_z = 210.0 - 0.50 * dense_pts[:, 0] + 2.2 * np.sin(dense_pts[:, 1] / 55.0)

    from scipy.spatial import cKDTree

    tree = cKDTree(dense_pts)
    grid_xy = np.column_stack([X.ravel(), Y.ravel()])
    dists, idxs = tree.query(grid_xy, distance_upper_bound=6.0)
    dists = dists.reshape(n, n)
    idxs = idxs.reshape(n, n)

    half_road = 1.75  # 3.5 m wide roadbed
    cut_fill_w = 4.2  # crisp ~38 deg cut/fill transition out to 4.2 m from centerline
    in_road_zone = dists < cut_fill_w
    switchback_mask = dists <= 2.5  # core roadbed + immediate scarp footprint for evaluation

    valid_idx = np.clip(idxs, 0, len(dense_pts) - 1)
    nearest_rz = road_z[valid_idx]
    blend = np.clip((dists - half_road) / (cut_fill_w - half_road), 0.0, 1.0)
    # Smoothstep / sharp cut-fill ramp
    w = 1.0 - blend
    dtm[in_road_zone] = w[in_road_zone] * nearest_rz[in_road_zone] + (1.0 - w[in_road_zone]) * dtm[in_road_zone]
    chm[dists <= half_road] = 0.5  # track canopy gap

    # 2. Carve 4 square 12 m x 12 m cut-and-fill transmission tower pads + OSM power=tower
    tower_centers_rel = [
        (45.0, 80.0),
        (50.0, 220.0),
        (248.0, 90.0),
        (252.0, 225.0),
    ]
    tower_masks = []
    osm_nodes: dict[str, dict[str, Any]] = {}
    tagged_features: list[dict[str, Any]] = []
    line_coords: list[list[float]] = []

    for idx_t, (tx, ty) in enumerate(tower_centers_rel, start=1):
        pad_half = 6.0  # 12 m x 12 m flat pad
        scarp_half = 8.5
        dx_t = np.abs(X - tx)
        dy_t = np.abs(Y - ty)
        cheb = np.maximum(dx_t, dy_t)
        in_pad = cheb <= pad_half
        in_scarp = cheb <= scarp_half
        pad_z = float(210.0 - 0.50 * tx + 2.2 * math.sin(ty / 55.0))
        blend_t = np.clip((cheb - pad_half) / (scarp_half - pad_half), 0.0, 1.0)
        wt = 1.0 - blend_t
        dtm[in_scarp] = wt[in_scarp] * pad_z + (1.0 - wt[in_scarp]) * dtm[in_scarp]
        chm[in_pad] = 0.4
        tower_masks.append(in_scarp)

        lon, lat = _TO_WGS84.transform(x0 + tx, y0 + ty)
        node_id = 990000 + idx_t
        osm_nodes[str(node_id)] = {
            "id": node_id,
            "lat": float(lat),
            "lon": float(lon),
            "tags": {"power": "tower", "ref": f"T-{idx_t}"},
        }
        tagged_features.append({
            "type": "node",
            "id": node_id,
            "lat": float(lat),
            "lon": float(lon),
            "tags": {"power": "tower", "ref": f"T-{idx_t}"},
        })
        line_coords.append([float(lon), float(lat)])

    osm_vectors = {
        "nodes": osm_nodes,
        "ways": {
            "995001": {
                "id": 995001,
                "nodes": [990001, 990002, 990003, 990004],
                "tags": {"power": "line"},
            }
        },
        "relations": {},
        "tagged_features": tagged_features + [
            {"type": "way", "id": 995001, "coords": line_coords, "tags": {"power": "line"}}
        ],
    }

    return {
        "dtm": dtm.astype(np.float32),
        "chm": chm.astype(np.float32),
        "rho_gnd": rho_gnd.astype(np.float32),
        "switchback_mask": switchback_mask,
        "switchback_polyline_rel": road_pts,
        "tower_masks": tower_masks,
        "tower_centers_6676": [(x0 + tx, y0 + ty) for tx, ty in tower_centers_rel],
        "osm_vectors": osm_vectors,
        "x0": x0,
        "y0": y0,
        "dx": dx,
    }


def _build_derivatives_bundle(dtm: np.ndarray, dx: float):
    """Build full DerivativeBundle using live palimpsest.derivatives."""
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


def run_self_test() -> dict[str, Any]:
    """Validate blackout TIN generator, switchback geometry, and OSM power=tower schema."""
    b = generate_blackout_patch_scene()
    assert b["dtm"].dtype == np.float32 and b["dtm"].shape == (400, 400)
    assert np.all(np.isfinite(b["dtm"]))
    assert float(b["rho_gnd"][b["blackout_mask"]].max()) == 0.0
    assert float(b["rho_gnd"][~b["blackout_mask"]].min()) >= 0.5
    blackout_area_m2 = float(b["blackout_mask"].sum()) * (b["dx"] ** 2)
    assert 400.0 <= blackout_area_m2 <= 600.0

    f = generate_firewall_decoy_scene()
    assert f["dtm"].dtype == np.float32 and f["dtm"].shape == (600, 600)
    assert np.all(np.isfinite(f["dtm"]))
    assert len(f["tower_centers_6676"]) == 4
    towers_tagged = [x for x in f["osm_vectors"]["tagged_features"] if x["tags"].get("power") == "tower"]
    assert len(towers_tagged) == 4
    sb_area_m2 = float(f["switchback_mask"].sum()) * (f["dx"] ** 2)
    assert sb_area_m2 > 1500.0

    return {
        "status": "PASS",
        "blackout_area_m2": blackout_area_m2,
        "switchback_footprint_m2": sb_area_m2,
        "tower_pad_count": len(towers_tagged),
    }


def run_tier1_firewall() -> dict[str, Any]:
    """Run Tier-1 Firewall Oracles against live `palimpsest.detector`."""
    from palimpsest.detector import detect_candidates

    # 1. Canopy-Dropout Blackout Patch Oracle
    b = generate_blackout_patch_scene()
    deriv_b = _build_derivatives_bundle(b["dtm"], b["dx"])
    res_b = detect_candidates(
        b["dtm"], b["chm"], b["rho_gnd"], deriv_b,
        osm_vectors=None, gsi_layers=None,
        x0=b["x0"], y0=b["y0"], dx=b["dx"],
        fdr_q=0.05, min_rho_gnd=0.5,
    )
    bx0, by0, bx1, by1 = b["blackout_bbox_6676"]
    blackout_survivors = []
    for c in res_b.survivors:
        pad = math.sqrt(max(c.area_m2, 1.0) / math.pi) + 2.0
        if (c.x_6676 + pad >= bx0) and (c.x_6676 - pad <= bx1) and (c.y_6676 + pad >= by0) and (c.y_6676 - pad <= by1):
            blackout_survivors.append(c.candidate_id)

    blackout_pass = (len(blackout_survivors) == 0)

    # 2. Forestry Switchback + OSM Transmission Tower Pad Firewall
    f = generate_firewall_decoy_scene()
    deriv_f = _build_derivatives_bundle(f["dtm"], f["dx"])
    res_f = detect_candidates(
        f["dtm"], f["chm"], f["rho_gnd"], deriv_f,
        osm_vectors=f["osm_vectors"], gsi_layers=None,
        x0=f["x0"], y0=f["y0"], dx=f["dx"],
        fdr_q=0.05, min_rho_gnd=0.5,
    )

    from scipy.spatial import cKDTree
    sb_tree = cKDTree(f["switchback_polyline_rel"] + np.array([[f["x0"], f["y0"]]]))

    sb_survivor_ids = []
    sb_survivor_area = 0.0
    tower_hits = [False] * len(f["tower_centers_6676"])
    tower_survivor_ids = []

    for c in res_f.survivors:
        d_sb, _ = sb_tree.query([c.x_6676, c.y_6676])
        if d_sb <= 6.0:
            sb_survivor_ids.append(c.candidate_id)
            sb_survivor_area += float(c.area_m2)
        for ti, (tx, ty) in enumerate(f["tower_centers_6676"]):
            if math.hypot(c.x_6676 - tx, c.y_6676 - ty) <= 12.0:
                tower_hits[ti] = True
                tower_survivor_ids.append(c.candidate_id)

    sb_total_area = float(f["switchback_mask"].sum()) * (f["dx"] ** 2)
    sb_surviving_frac = min(1.0, sb_survivor_area / max(sb_total_area, 1.0))
    tower_surviving_frac = sum(tower_hits) / len(tower_hits)
    # Combined decoy footprint area: switchback + 4 pads (17m x 17m each)
    total_decoy_area = sb_total_area + 4.0 * (17.0 * 17.0)
    surviving_decoy_area = sb_survivor_area + sum(
        c.area_m2 for c in res_f.survivors if c.candidate_id in set(tower_survivor_ids)
    )
    overall_rejection_rate = 1.0 - min(1.0, surviving_decoy_area / max(total_decoy_area, 1.0))

    firewall_pass = (
        sb_surviving_frac <= 0.05
        and tower_surviving_frac <= 0.05
        and overall_rejection_rate >= 0.95
    )

    return {
        "oracle": "tier1_firewall",
        "status": "PASS" if (blackout_pass and firewall_pass) else "FAIL",
        "blackout_patch": {
            "total_survivors": len(res_b.survivors),
            "overlapping_blackout_survivors": blackout_survivors,
            "pass": blackout_pass,
        },
        "switchback_and_osm_firewall": {
            "total_survivors": len(res_f.survivors),
            "switchback_survivor_ids": sb_survivor_ids,
            "switchback_surviving_area_frac": sb_surviving_frac,
            "tower_pads_survived": sum(tower_hits),
            "tower_pads_total": len(tower_hits),
            "tower_survivor_ids": tower_survivor_ids,
            "overall_rejection_rate": overall_rejection_rate,
            "pass": firewall_pass,
        },
    }
