import gzip

import numpy as np
import rasterio

from palimpsest.coverage import context_density, coverage_codes, write_density_map
from palimpsest.lidar import StudyZoneGrid


def test_boundaries_and_blackout_precedence():
    context = np.array([6., .4, .5, 1, 2.5, 5.])
    actual = np.ones_like(context)
    actual[0] = .49
    np.testing.assert_array_equal(coverage_codes(actual, context), np.arange(6))


def test_native_and_viewer_rasters_share_cell_coordinates(tmp_path):
    rho = np.full((40, 42), 6., dtype=np.float32)
    rho[:6] = 0.
    grid = StudyZoneGrid(rho, rho, rho, rho, 0, 100, .5, 6676, 0.)
    write_density_map(tmp_path, grid)
    with rasterio.open(tmp_path/"ground_coverage.tif") as ds:
        north_first = ds.read(1)
        assert ds.xy(0, 0) == (.25, 119.75)
    browser = np.frombuffer(gzip.decompress((tmp_path/"ground_coverage.u8.gz").read_bytes()), dtype=np.uint8)
    np.testing.assert_array_equal(north_first[::-1], browser.reshape(rho.shape))
    assert np.all(north_first[-1] == 0)
    assert np.all(north_first[0] == 5)
    # The unobserved area outside the study zone must not dilute the average.
    mean = context_density(rho, .5)
    assert mean[-1, 0] == 6.
    assert mean[16, 16] == np.mean(rho[:32, :32])


def test_candidate_summary_includes_blackout_neighbors(tmp_path):
    import json
    from types import SimpleNamespace

    from palimpsest.coverage import write_candidate_support

    rho = np.ones((40, 40), dtype=np.float32)
    rho[:, :20] = 0
    grid = StudyZoneGrid(rho, rho, rho, rho, 0., 0., .5, 6676, 0.)
    candidate = SimpleNamespace(candidate_id="PLMP-0001", x_6676=10.25, y_6676=10.25)
    write_density_map(tmp_path, grid)
    write_candidate_support(tmp_path, grid, SimpleNamespace(candidates=[candidate]))
    info = json.loads((tmp_path/"field_support.json").read_text())["candidates"][candidate.candidate_id]
    assert info["window_cells"] == 1024
    assert info["native_band_cells"] == [512, 0, 512, 0, 0]
    assert info["center_rho"] == 1. and info["mean_16m"] == .5
    assert info["code"] == 2
