import os
import math
import numpy as np
from scipy.ndimage import gaussian_filter

from palimpsest.derivatives import compute_all_derivatives
from palimpsest.detector import detect_candidates
from palimpsest.lidar import run_csf_tile


def test_csf_tempdir_cleanliness_and_ground_separation(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rng = np.random.default_rng(7)
    # 40m x 40m ground plane + dense elevated canopy
    gx = rng.uniform(0.0, 40.0, 1500)
    gy = rng.uniform(0.0, 40.0, 1500)
    gz = 100.0 + 0.1 * gx + rng.normal(0.0, 0.03, 1500)

    cx = rng.uniform(0.0, 40.0, 3000)
    cy = rng.uniform(0.0, 40.0, 3000)
    cz = 100.0 + 0.1 * cx + rng.uniform(8.0, 20.0, 3000)

    xyz = np.column_stack((np.concatenate([gx, cx]), np.concatenate([gy, cy]), np.concatenate([gz, cz])))
    mask = run_csf_tile(xyz, cloth_resolution=0.75, rigidness=2, class_threshold=0.30)

    assert list(tmp_path.iterdir()) == []
    assert mask.shape == (4500,)
    assert mask.dtype == bool
    # Ground points should be classified mostly True, canopy strictly False
    assert np.mean(mask[:1500]) > 0.90
    assert np.mean(mask[1500:]) < 0.02


def test_provenance_blackout_firewall_zero_detections():
    dx = 0.5
    ny, nx = 200, 200  # 100m x 100m
    y = np.arange(ny, dtype=np.float32)[:, None] * dx
    x = np.arange(nx, dtype=np.float32)[None, :] * dx
    # Steep slope with an artificial flat TIN facet inside a 20m blackout hole
    dem = np.broadcast_to(150.0 - 0.5 * x, (ny, nx)).astype(np.float32).copy()
    rho = np.full((ny, nx), 2.5, dtype=np.float32)

    # Create a flat terrace-like TIN facet inside a 24m x 24m blackout patch (rho_gnd = 0)
    in_hole = (x >= 38.0) & (x <= 62.0) & (y >= 38.0) & (y <= 62.0)
    dem[in_hole] = 125.0
    rho[in_hole] = 0.0
    chm = np.full((ny, nx), 15.0, dtype=np.float32)

    derivs = compute_all_derivatives(dem, dx=dx)
    res = detect_candidates(dem, chm, rho, derivs, dx=dx, min_rho_gnd=0.5)
    assert len(res.survivors) == 0
    assert res.funnel["survivors_total"] == 0


def test_detect_three_morphologies_and_reject_switchback_and_osm():
    dx = 0.5
    ny, nx = 400, 400  # 200m x 200m
    y = np.arange(ny, dtype=np.float32)[:, None] * dx
    x = np.arange(nx, dtype=np.float32)[None, :] * dx

    # Natural hillslope sloping Westward (-0.45 * x) with a N-S ridge on the right
    dem = np.broadcast_to(180.0 - 0.45 * np.abs(x - 140.0), (ny, nx)).astype(np.float32).copy()
    rho = np.full((ny, nx), 3.0, dtype=np.float32)
    chm = np.full((ny, nx), 14.0, dtype=np.float32)

    # 1) Inject a compact 14m x 14m flat kuruwa terrace at (x=60, y=60)
    pad = (x >= 53.0) & (x <= 67.0) & (y >= 53.0) & (y <= 67.0)
    dem[pad] = float(np.mean(dem[pad]))

    # 2) Inject a circular mound at (x=60, y=140), radius=6m, height=1.8m
    r_m = np.hypot(x - 60.0, y - 140.0)
    dem += (1.8 * np.maximum(0.0, 1.0 - (r_m / 6.0) ** 2)).astype(np.float32)

    # 3) Inject a ridge-cutting horikiri trench across the N-S ridge at y=100, x in [128, 152]
    hori_w = np.exp(-((y - 100.0) ** 2) / (2.0 * 2.5 ** 2)) * np.exp(-((x - 140.0) ** 2) / (2.0 * 8.0 ** 2))
    dem -= (2.5 * hori_w).astype(np.float32)

    # 4) Inject a 3.5m wide contour-following forestry switchback road along x=90, y in [10, 170]
    road = (np.abs(x - 90.0) <= 1.75) & (y >= 10.0) & (y <= 170.0)
    dem[road] = float(np.mean(dem[road]))

    # 5) Inject a modern OSM tower pad at (x=40, y=100)
    tower_pad = (x >= 35.0) & (x <= 45.0) & (y >= 95.0) & (y <= 105.0)
    dem[tower_pad] = float(np.mean(dem[tower_pad]))

    dem = gaussian_filter(dem, sigma=0.6, mode="nearest").astype(np.float32)
    osm_vectors = [
        {"type": "node", "id": 999, "x": 40.0, "y": 100.0, "tags": {"power": "tower"}},
    ]
    # Note: detect_candidates maps OSM lat/lon unless x_6676/y_6676 or x/y is given
    derivs = compute_all_derivatives(dem, dx=dx)
    res = detect_candidates(dem, chm, rho, derivs, osm_vectors=osm_vectors, x0=0.0, y0=0.0, dx=dx)

    surv_morphs = {c.morphology for c in res.survivors}
    assert "terrace" in surv_morphs
    assert "mound_pit" in surv_morphs
    assert "horikiri" in surv_morphs

    # Verify tower pad was rejected as osm_modern
    assert any(c.rejection_reason == "osm_modern" for c in res.candidates)
    # Verify no survivor lies on the 3.5m switchback road (x ~ 90) or OSM tower (x ~ 40, y ~ 100)
    for s in res.survivors:
        assert abs(s.x_6676 - 90.0) > 4.0
        assert math.hypot(s.x_6676 - 40.0, s.y_6676 - 100.0) > 15.0
