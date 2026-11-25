import math
import numpy as np
import pytest

from palimpsest.derivatives import (
    benjamini_hochberg_fdr,
    compute_dinf_flow,
    compute_drainage_violation,
    compute_lrm,
    compute_openness,
    compute_rrim,
    compute_svf,
    compute_vat,
)


def _make_grid(span_m: float = 60.0, dx: float = 0.25):
    n = int(round(span_m / dx)) | 1
    c = n // 2
    coords = (np.arange(n) - c) * dx
    X, Y = np.meshgrid(coords, coords)
    return X, Y, c, dx


def test_openness_and_svf_paraboloid():
    X, Y, c, dx = _make_grid(40.0, dx=0.25)
    parab = (-0.02 * (X ** 2 + Y ** 2)).astype(np.float32)
    phi, psi, diff_I = compute_openness(parab, dx=dx, L=10.0, n_azimuths=16)
    svf = compute_svf(parab, dx=dx, L=10.0, n_azimuths=16)
    assert abs(float(phi[c, c]) - math.pi / 2.0) / (math.pi / 2.0) < 0.01
    assert float(diff_I[c, c]) > 0.0
    assert abs(float(svf[c, c]) - 1.0) < 0.005


def test_openness_and_svf_v_trench():
    X, Y, c, dx = _make_grid(60.0, dx=0.25)
    v_trench = np.minimum(0.5 * np.abs(X), 6.0).astype(np.float32)
    phi, psi, diff_I = compute_openness(v_trench, dx=dx, L=10.0, n_azimuths=16)
    svf = compute_svf(v_trench, dx=dx, L=10.0, n_azimuths=16)

    alphas = 2.0 * math.pi * np.arange(16) / 16.0
    beta_exact = np.arctan(0.5 * np.abs(np.cos(alphas)))
    phi_exact = float(np.mean(math.pi / 2.0 - beta_exact))
    svf_exact = float(1.0 - np.mean(np.sin(beta_exact)))

    assert abs(float(phi[c, c]) - phi_exact) / phi_exact < 0.01
    assert abs(float(svf[c, c]) - svf_exact) / svf_exact < 0.01
    assert float(diff_I[c, c]) < 0.0


def test_openness_and_svf_cylindrical_pit():
    X, Y, c, dx = _make_grid(60.0, dx=0.2)
    R = np.hypot(X, Y)
    r_pit, h_pit = 10.0, 4.0
    pit = np.where(R < r_pit, -h_pit, 0.0).astype(np.float32)
    phi, psi, diff_I = compute_openness(pit, dx=dx, L=15.0, n_azimuths=16)
    svf = compute_svf(pit, dx=dx, L=15.0, n_azimuths=16)

    beta_exact = math.atan(h_pit / r_pit)
    phi_exact = math.pi / 2.0 - beta_exact
    svf_exact = 1.0 - math.sin(beta_exact)
    assert abs(float(phi[c, c]) - phi_exact) / phi_exact < 0.01
    assert abs(float(svf[c, c]) - svf_exact) / svf_exact < 0.01
    assert float(diff_I[c, c]) < 0.0


@pytest.mark.parametrize(
    "gx,gy",
    [
        (-1.0, -1.0),
        (0.3, -0.7),
        (-0.8, 0.2),
        (0.5, 0.5),
        (0.0, -1.0),
        (1.0, 0.0),
        (-0.4, -0.9),
        (0.9, -0.1),
    ],
)
def test_dinf_tilted_planes(gx, gy):
    X, Y, c, dx = _make_grid(20.0, dx=0.5)
    plane = (gx * X + gy * Y).astype(np.float32)
    ang, area, slope = compute_dinf_flow(plane, dx=dx)
    expected = math.atan2(-gy, -gx) % (2.0 * math.pi)
    got = float(ang[c, c])
    err_deg = abs(math.degrees(math.atan2(math.sin(got - expected), math.cos(got - expected))))
    assert err_deg < 0.5
    assert abs(float(slope[c, c]) - math.atan(math.hypot(gx, gy))) < 1e-3
    assert np.all(area >= dx * dx - 1e-6)


def test_rrim_vat_lrm_and_drainage_violation():
    X, Y, c, dx = _make_grid(60.0, dx=0.5)
    # Tilted slope with a flat bench in center
    dem = (-0.45 * X).astype(np.float32)
    # Mound in upper quadrant
    r_mound = np.hypot(X - 10.0, Y - 10.0)
    dem += (1.5 * np.exp(-(r_mound ** 2) / (2.0 * 3.0 ** 2))).astype(np.float32)

    rrim = compute_rrim(dem, dx=dx)
    assert rrim.shape == (*dem.shape, 3) and rrim.dtype == np.uint8

    vat = compute_vat(dem, dx=dx)
    assert vat.shape == (*dem.shape, 3) and vat.dtype == np.uint8

    lrm = compute_lrm(dem, dx=dx, radius_m=15.0)
    mound_idx_r = int(round(10.0 / dx)) + c
    mound_idx_c = int(round(10.0 / dx)) + c
    assert float(lrm[mound_idx_r, mound_idx_c]) > 0.9

    ang, area, sl = compute_dinf_flow(dem, dx=dx)
    dv = compute_drainage_violation(dem, ang, area, sl, dx=dx)
    assert dv.dtype == np.float32
    assert float(dv.min()) >= 0.0 and float(dv.max()) <= 1.0


def test_benjamini_hochberg_fdr():
    p = np.array([0.001, 0.004, 0.02, 0.04, 0.5, 0.8])
    rej, cutoff = benjamini_hochberg_fdr(p, q=0.05)
    # Ranks: 1->0.00833, 2->0.01667, 3->0.025 (0.02<=0.025), 4->0.0333 (0.04>0.0333)
    assert rej.tolist() == [True, True, True, False, False, False]
    assert abs(cutoff - 0.02) < 1e-12

    rej_null, cutoff_null = benjamini_hochberg_fdr(np.array([0.2, 0.5, 0.9]), q=0.05)
    assert not np.any(rej_null)
    assert cutoff_null == 0.0
