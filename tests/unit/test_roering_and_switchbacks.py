import math
import numpy as np
from scipy.ndimage import gaussian_filter

from palimpsest.derivatives import compute_all_derivatives
from palimpsest.detector import detect_candidates


def _roering_creep(dem: np.ndarray, dx: float, years: float, K: float = 0.002, Sc: float = 1.25) -> np.ndarray:
    """Explicit finite-difference solver for Roering et al. (1999) nonlinear soil creep."""
    z = dem.astype(np.float64, copy=True)
    dt = 2.0  # yr per step (stable for dx=0.5, K=0.008)
    n_steps = max(1, int(round(years / dt)))
    for _ in range(n_steps):
        gy, gx = np.gradient(z, dx)
        g2 = gx * gx + gy * gy
        denom = np.maximum(0.1, 1.0 - g2 / (Sc * Sc))
        qx = -K * gx / denom
        qy = -K * gy / denom
        _, dqx = np.gradient(qx, dx)
        dqy, _ = np.gradient(qy, dx)
        z[1:-1, 1:-1] -= dt * (dqx[1:-1, 1:-1] + dqy[1:-1, 1:-1])
    return z.astype(np.float32)


def test_roering_weathered_ruins_across_ages():
    dx = 0.5
    ny, nx = 440, 440  # 220m x 220m
    y = np.arange(ny, dtype=np.float32)[:, None] * dx
    x = np.arange(nx, dtype=np.float32)[None, :] * dx

    base = np.broadcast_to(200.0 - 0.42 * np.abs(x - 160.0), (ny, nx)).astype(np.float32).copy()
    rho = np.full((ny, nx), 2.5, dtype=np.float32)
    chm = np.full((ny, nx), 15.0, dtype=np.float32)

    # Inject 3 features: terrace, mound, horikiri
    pad = (x >= 48.0) & (x <= 64.0) & (y >= 48.0) & (y <= 64.0)
    base[pad] = float(np.mean(base[pad]))
    r_m = np.hypot(x - 60.0, y - 160.0)
    base += (1.6 * np.maximum(0.0, 1.0 - (r_m / 6.0) ** 2)).astype(np.float32)
    hori_w = np.exp(-((y - 110.0) ** 2) / (2.0 * 3.0 ** 2)) * np.exp(-((x - 160.0) ** 2) / (2.0 * 9.0 ** 2))
    base -= (2.4 * hori_w).astype(np.float32)

    for age in (100.0, 300.0, 800.0):
        dem = _roering_creep(base, dx=dx, years=age)
        derivs = compute_all_derivatives(dem, dx=dx)
        res = detect_candidates(dem, chm, rho, derivs, dx=dx)
        morphs = {s.morphology for s in res.survivors}
        assert "terrace" in morphs, f"Failed terrace at {age} yr: {res.survivors}"
        assert "mound_pit" in morphs, f"Failed mound_pit at {age} yr: {res.survivors}"
        assert "horikiri" in morphs, f"Failed horikiri at {age} yr: {res.survivors}"


def test_curved_hairpin_forestry_switchback_rejected():
    dx = 0.5
    ny, nx = 500, 500  # 250m x 250m
    y = np.arange(ny, dtype=np.float32)[:, None] * dx
    x = np.arange(nx, dtype=np.float32)[None, :] * dx
    dem = np.broadcast_to(200.0 - 0.45 * x, (ny, nx)).astype(np.float32).copy()
    rho = np.full((ny, nx), 3.0, dtype=np.float32)
    chm = np.full((ny, nx), 14.0, dtype=np.float32)

    # Carve a sinusoidal / hairpin 3.5m wide cut-and-fill switchback road
    t_vals = np.linspace(20.0, 230.0, 1200)
    road_x = 125.0 + 30.0 * np.sin(0.04 * (t_vals - 20.0))
    road_y = t_vals
    for rx, ry in zip(road_x, road_y):
        m = ((x - rx) ** 2 + (y - ry) ** 2) <= (1.75 ** 2)
        dem[m] = 200.0 - 0.45 * rx
    dem = gaussian_filter(dem, sigma=0.5, mode="nearest").astype(np.float32)

    derivs = compute_all_derivatives(dem, dx=dx)
    res = detect_candidates(dem, chm, rho, derivs, dx=dx)
    # Must achieve >= 95% rejection (ideally 0 terrace survivors on the switchback)
    terrace_survivors = [s for s in res.survivors if s.morphology == "terrace"]
    assert len(terrace_survivors) == 0, f"Switchback leaked terrace survivors: {terrace_survivors}"
