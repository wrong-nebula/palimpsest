import xml.etree.ElementTree as ET
from pathlib import Path
import numpy as np

from palimpsest.detector import CandidateRecord, DetectionResult
from palimpsest.export import (
    crop_gsi_textures,
    read_binary_pack,
    write_binary_pack,
    write_candidates_json,
    write_waypoints_gpx,
)


def test_binary_pack_roundtrip(tmp_path):
    ny, nx = 400, 400
    rng = np.random.default_rng(123)
    layers = {
        "z_gnd": rng.uniform(80.0, 120.0, (ny, nx)).astype(np.float32),
        "chm": rng.uniform(0.0, 25.0, (ny, nx)).astype(np.float32),
        "rho_gnd": rng.uniform(0.5, 4.0, (ny, nx)).astype(np.float32),
        "rrim_r": rng.uniform(0.0, 1.0, (ny, nx)).astype(np.float32),
        "rrim_g": rng.uniform(0.0, 1.0, (ny, nx)).astype(np.float32),
        "rrim_b": rng.uniform(0.0, 1.0, (ny, nx)).astype(np.float32),
        "svf": rng.uniform(0.3, 1.0, (ny, nx)).astype(np.float32),
        "lrm": rng.normal(0.0, 0.5, (ny, nx)).astype(np.float32),
        "openness_diff": rng.normal(0.0, 0.1, (ny, nx)).astype(np.float32),
        "flow_violation": rng.uniform(0.0, 1.0, (ny, nx)).astype(np.float32),
    }
    pts = rng.uniform(0.0, 200.0, (1024, 4)).astype(np.float32)

    pack_path = tmp_path / "PLMP-0001.bin"
    write_binary_pack(pack_path, x0=-44000.0, y0=-144500.0, dx=0.5, layers=layers, canopy_pts=pts)

    loaded = read_binary_pack(pack_path)
    assert loaded["version"] == 1
    assert loaded["nx"] == 400 and loaded["ny"] == 400
    assert loaded["x0"] == -44000.0 and loaded["y0"] == -144500.0
    assert abs(loaded["dx"] - 0.5) < 1e-6
    assert loaded["n_layers"] == 10
    assert loaded["n_canopy_pts"] == 1024
    for k, arr in layers.items():
        np.testing.assert_allclose(loaded["layers"][k], arr, rtol=1e-6, atol=1e-6)
    np.testing.assert_allclose(loaded["canopy_pts"], pts, rtol=1e-6, atol=1e-6)


def test_gpx_and_candidates_json_export(tmp_path):
    rec = CandidateRecord(
        candidate_id="PLMP-0001",
        morphology="terrace",
        status="survivor",
        temporal_class="Class A",
        rejection_reason=None,
        x_6676=-43800.0,
        y_6676=-144400.0,
        lat=34.6975,
        lon=138.0215,
        area_m2=180.0,
        wall_height_m=2.1,
        scarp_slope_deg=36.0,
        local_relief_m=1.4,
        mean_rho_gnd=2.2,
        min_rho_gnd=0.9,
        upslope_area_m2=18.0,
        drainage_violation=0.82,
        p_value=1e-4,
        q_value=0.002,
        confidence_score=0.91,
        osm_match=None,
        historical_notes="Pre-modern canopy-hidden terrace",
        pack_file="packs/PLMP-0001.bin",
        textures={"ort_USA10": None, "ort_old10": "packs/textures/PLMP-0001/ort_old10.png", "gazo1": None, "seamlessphoto": None},
    )
    det = DetectionResult(
        candidates=[rec],
        survivors=[rec],
        funnel={
            "raw_peaks_or_cells": 5,
            "after_rho_gnd_gate": 4,
            "after_morphology_filter": 3,
            "after_bh_fdr": 2,
            "after_geomorphic_falsifier": 1,
            "after_osm_historical_diff": 1,
            "survivors_total": 1,
        },
        fdr_threshold=0.01,
    )
    dtm = np.full((100, 100), 142.5, dtype=np.float32)
    gpx_path = write_waypoints_gpx(tmp_path / "out.gpx", [rec], dtm, x0=-43825.0, y0=-144425.0, dx=0.5)
    tree = ET.parse(gpx_path)
    root = tree.getroot()
    ns = {"gpx": "http://www.topografix.com/GPX/1/1"}
    wpts = root.findall("gpx:wpt", ns)
    assert len(wpts) == 1
    assert wpts[0].find("gpx:name", ns).text == "PLMP-0001"
    assert wpts[0].find("gpx:sym", ns).text == "Flag, Red"
    assert wpts[0].find("gpx:ele", ns).text == "142.50"

    json_path = write_candidates_json(tmp_path / "candidates.json", det, {})
    assert json_path.is_file()


def test_crop_real_cached_gsi_textures(tmp_path):
    cache_gsi = Path("data/cache/gsi")
    if not cache_gsi.is_dir():
        return
    tex = crop_gsi_textures("data/cache", tmp_path, "PLMP-TEST", x0_cut=-43900.0, y0_cut=-144500.0, size_m=200.0, tex_px=128)
    assert tex["ort_USA10"] is None
    assert tex["ort_old10"] is not None and (tmp_path / tex["ort_old10"]).is_file()
    assert tex["gazo1"] is not None and (tmp_path / tex["gazo1"]).is_file()
    assert tex["seamlessphoto"] is not None and (tmp_path / tex["seamlessphoto"]).is_file()
