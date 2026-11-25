"""Tier 1 Analytical Oracles for PALIMPSEST.

Independently verifies:
1. Yokoyama et al. (2002) Positive/Negative Openness (Phi_L, Psi_L) and
   Zaksek et al. (2011) Sky-View Factor (SVF) against exact closed-form
   integrals / high-precision line quadrature on:
   - Paraboloid: z = a * (x^2 + y^2)
   - V-trench: z = s * |x|
   - Cylindrical pit: z = -H for r < R, 0 outside
   across L in {10, 25, 50} m, n_azimuths=16, asserting mean relative error < 1%.
2. Tarboton (1997) D-infinity flow azimuth on tilted planes z = a*x + b*y + c
   across non-cardinal, non-diagonal angles, asserting angular error < 0.5 deg
   relative to -grad(z) / |grad(z)|.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np


def make_grid(extent_m: float = 160.0, dx: float = 0.5) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Create a centered right-handed grid matching CONTRACT.md §2.1.

    col increases Eastward (+X), row increases Northward (+Y).
    Returns (X, Y, coords_1d) where X, Y have shape (ny, nx).
    """
    n = int(round(extent_m / dx))
    half = 0.5 * extent_m
    xs = -half + (np.arange(n, dtype=np.float64) + 0.5) * dx
    ys = -half + (np.arange(n, dtype=np.float64) + 0.5) * dx
    X, Y = np.meshgrid(xs, ys, indexing="xy")
    return X, Y, xs


# ---------------------------------------------------------------------------
# Exact Closed-Form Analytical Oracles (Continuous Surface Integrals)
# ---------------------------------------------------------------------------

def exact_paraboloid_openness_svf(
    x: np.ndarray,
    y: np.ndarray,
    a: float,
    L: float,
    n_azimuths: int = 16,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Exact closed-form (Phi_L, Psi_L, SVF) on z = a * (x^2 + y^2), a > 0.

    Along unit ray u_k = (cos a_k, sin a_k) at distance d in (0, L]:
      (z(p + d*u_k) - z(p)) / d = a * (2 * dot(p, u_k) + d)
    Since a > 0, this is strictly increasing in d:
      - supremum over d in (0, L] occurs at d = L: tan(beta) = a * (2*dot(p,u_k) + L)
      - infimum (for nadir delta) occurs as d -> 0+: tan(delta) = -2*a*dot(p,u_k)
    """
    alphas = 2.0 * np.pi * np.arange(n_azimuths, dtype=np.float64) / n_azimuths
    phi_sum = np.zeros_like(x, dtype=np.float64)
    psi_sum = np.zeros_like(x, dtype=np.float64)
    sin_gamma_sum = np.zeros_like(x, dtype=np.float64)

    for alpha in alphas:
        ux = math.cos(alpha)
        uy = math.sin(alpha)
        proj = x * ux + y * uy
        beta = np.arctan(a * (2.0 * proj + L))
        delta = np.arctan(-2.0 * a * proj)
        phi_sum += (0.5 * np.pi - beta)
        psi_sum += (0.5 * np.pi - delta)
        gamma = np.maximum(0.0, beta)
        sin_gamma_sum += np.sin(gamma)

    phi = phi_sum / n_azimuths
    psi = psi_sum / n_azimuths
    svf = 1.0 - sin_gamma_sum / n_azimuths
    return phi, psi, svf


def exact_vtrench_openness_svf(
    x: np.ndarray,
    y: np.ndarray,
    s: float,
    L: float,
    n_azimuths: int = 16,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Exact closed-form (Phi_L, Psi_L, SVF) on V-trench z = s * |x|, s > 0."""
    alphas = 2.0 * np.pi * np.arange(n_azimuths, dtype=np.float64) / n_azimuths
    phi_sum = np.zeros_like(x, dtype=np.float64)
    psi_sum = np.zeros_like(x, dtype=np.float64)
    sin_gamma_sum = np.zeros_like(x, dtype=np.float64)

    abs_x = np.abs(x)
    sign_x = np.where(x >= 0.0, 1.0, -1.0)

    for alpha in alphas:
        ca = math.cos(alpha)
        # On x == 0: slope along ray is s * |ca| identically for all d > 0
        at_axis = (abs_x == 0.0)
        ux = sign_x * ca  # effective cos relative to outward flank normal

        tan_beta = np.empty_like(x, dtype=np.float64)
        tan_delta = np.empty_like(x, dtype=np.float64)

        # Off-axis: ux >= 0 -> ray stays on same flank -> constant slope s*ux
        same_flank = (~at_axis) & (ux >= 0.0)
        tan_beta[same_flank] = s * ux[same_flank]
        tan_delta[same_flank] = -s * ux[same_flank]

        # Off-axis: ux < 0 -> ray crosses x=0 at d0 = |x| / (-ux)
        cross_flank = (~at_axis) & (ux < 0.0)
        if np.any(cross_flank):
            d0 = abs_x[cross_flank] / (-ux[cross_flank])
            ux_c = ux[cross_flank]
            ax_c = abs_x[cross_flank]
            # For d <= d0, f(d) = s*ux_c. For d > d0, f(d) = -s*ux_c - 2*s*|x|/d (inc in d)
            far_val = -s * ux_c - 2.0 * s * ax_c / L
            tan_beta[cross_flank] = np.where(L > d0, np.maximum(s * ux_c, far_val), s * ux_c)
            tan_delta[cross_flank] = -s * ux_c

        tan_beta[at_axis] = s * abs(ca)
        tan_delta[at_axis] = -s * abs(ca)

        beta = np.arctan(tan_beta)
        delta = np.arctan(tan_delta)
        phi_sum += (0.5 * np.pi - beta)
        psi_sum += (0.5 * np.pi - delta)
        sin_gamma_sum += np.sin(np.maximum(0.0, beta))

    phi = phi_sum / n_azimuths
    psi = psi_sum / n_azimuths
    svf = 1.0 - sin_gamma_sum / n_azimuths
    return phi, psi, svf


def exact_cylindrical_pit_openness_svf(
    x: np.ndarray,
    y: np.ndarray,
    R: float,
    H: float,
    L: float,
    n_azimuths: int = 16,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Exact closed-form (Phi_L, Psi_L, SVF) on cylindrical pit:
    z(r) = -H for r < R, 0 for r >= R (H > 0, R > 0).
    """
    alphas = 2.0 * np.pi * np.arange(n_azimuths, dtype=np.float64) / n_azimuths
    phi_sum = np.zeros_like(x, dtype=np.float64)
    psi_sum = np.zeros_like(x, dtype=np.float64)
    sin_gamma_sum = np.zeros_like(x, dtype=np.float64)

    r2 = x * x + y * y
    inside = r2 < (R * R)

    for alpha in alphas:
        ux = math.cos(alpha)
        uy = math.sin(alpha)
        proj = x * ux + y * uy
        disc = proj * proj + (R * R - r2)

        tan_beta = np.zeros_like(x, dtype=np.float64)
        tan_delta = np.zeros_like(x, dtype=np.float64)

        # Inside pit: ray hits rim at d_rim = -proj + sqrt(disc)
        if np.any(inside):
            d_rim = -proj[inside] + np.sqrt(np.maximum(0.0, disc[inside]))
            tan_beta[inside] = np.where((d_rim > 0.0) & (d_rim <= L), H / np.maximum(d_rim, 1e-12), 0.0)
            tan_delta[inside] = 0.0

        # Outside pit: rim is at or below z=0 -> beta = 0; ray enters pit if disc > 0 & proj < 0
        outside = ~inside
        if np.any(outside):
            hits = outside & (disc > 0.0) & (proj < 0.0)
            if np.any(hits):
                d_near = -proj[hits] - np.sqrt(np.maximum(0.0, disc[hits]))
                tan_delta[hits] = np.where((d_near > 0.0) & (d_near <= L), H / np.maximum(d_near, 1e-12), 0.0)

        beta = np.arctan(tan_beta)
        delta = np.arctan(tan_delta)
        phi_sum += (0.5 * np.pi - beta)
        psi_sum += (0.5 * np.pi - delta)
        sin_gamma_sum += np.sin(np.maximum(0.0, beta))

    phi = phi_sum / n_azimuths
    psi = psi_sum / n_azimuths
    svf = 1.0 - sin_gamma_sum / n_azimuths
    return phi, psi, svf


def _quadrature_openness_svf(
    surface_fn,
    x: np.ndarray,
    y: np.ndarray,
    L: float,
    n_azimuths: int = 16,
    n_radial: int = 4000,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """High-precision continuous line-search quadrature to independently verify closed-form formulas."""
    alphas = 2.0 * np.pi * np.arange(n_azimuths, dtype=np.float64) / n_azimuths
    ds = np.linspace(1e-3, L, n_radial, dtype=np.float64)
    z0 = surface_fn(x, y)

    phi_sum = np.zeros_like(x, dtype=np.float64)
    psi_sum = np.zeros_like(x, dtype=np.float64)
    sin_gamma_sum = np.zeros_like(x, dtype=np.float64)

    for alpha in alphas:
        ux, uy = math.cos(alpha), math.sin(alpha)
        # shape: (..., n_radial)
        xr = x[..., None] + ds * ux
        yr = y[..., None] + ds * uy
        zr = surface_fn(xr, yr)
        slopes = (zr - z0[..., None]) / ds
        beta = np.arctan(np.max(slopes, axis=-1))
        delta = np.arctan(np.max(-slopes, axis=-1))
        phi_sum += (0.5 * np.pi - beta)
        psi_sum += (0.5 * np.pi - delta)
        sin_gamma_sum += np.sin(np.maximum(0.0, beta))

    return phi_sum / n_azimuths, psi_sum / n_azimuths, 1.0 - sin_gamma_sum / n_azimuths


def _reference_raster_openness_svf(
    dem: np.ndarray,
    dx: float,
    L: float,
    n_azimuths: int = 16,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Independent raster ray-marcher at step dx (bilinear) used for --self-test validation."""
    from scipy.ndimage import map_coordinates

    ny, nx = dem.shape
    rows = np.arange(ny, dtype=np.float64)
    cols = np.arange(nx, dtype=np.float64)
    C, R = np.meshgrid(cols, rows, indexing="xy")

    n_steps = max(1, int(round(L / dx)))
    ds_pix = np.arange(1, n_steps + 1, dtype=np.float64)
    ds_m = ds_pix * dx
    alphas = 2.0 * np.pi * np.arange(n_azimuths, dtype=np.float64) / n_azimuths

    phi_sum = np.zeros_like(dem, dtype=np.float64)
    psi_sum = np.zeros_like(dem, dtype=np.float64)
    sin_gamma_sum = np.zeros_like(dem, dtype=np.float64)

    dem64 = dem.astype(np.float64)
    for alpha in alphas:
        ca, sa = math.cos(alpha), math.sin(alpha)
        max_up = np.full_like(dem64, -np.inf)
        max_dn = np.full_like(dem64, -np.inf)
        for step_pix, step_m in zip(ds_pix, ds_m):
            rr = R + step_pix * sa
            cc = C + step_pix * ca
            z_s = map_coordinates(dem64, [rr, cc], order=1, mode="nearest")
            sl = (z_s - dem64) / step_m
            max_up = np.maximum(max_up, sl)
            max_dn = np.maximum(max_dn, -sl)
        beta = np.arctan(max_up)
        delta = np.arctan(max_dn)
        phi_sum += (0.5 * np.pi - beta)
        psi_sum += (0.5 * np.pi - delta)
        sin_gamma_sum += np.sin(np.maximum(0.0, beta))

    return phi_sum / n_azimuths, psi_sum / n_azimuths, 1.0 - sin_gamma_sum / n_azimuths


def _reference_dinf_plane_test(dem: np.ndarray, dx: float) -> np.ndarray:
    """Tarboton (1997) D-infinity flow angle for --self-test validation."""
    ny, nx = dem.shape
    z = dem.astype(np.float64)
    # 8 facets: (e1 offset (dr, dc), e2 offset (dr, dc), ac_angle_rad, af_sign)
    # Using Tarboton Table 1 mapped to (row=+North, col=+East) CCW from +East:
    # Facet 0: E=(0,+1), NE=(+1,+1) -> angle = r in [0, pi/4]
    # Facet 1: N=(+1,0), NE=(+1,+1) -> angle = pi/2 - r
    # Facet 2: N=(+1,0), NW=(+1,-1) -> angle = pi/2 + r
    # Facet 3: W=(0,-1), NW=(+1,-1) -> angle = pi - r
    # Facet 4: W=(0,-1), SW=(-1,-1) -> angle = pi + r
    # Facet 5: S=(-1,0), SW=(-1,-1) -> angle = 3pi/2 - r
    # Facet 6: S=(-1,0), SE=(-1,+1) -> angle = 3pi/2 + r
    # Facet 7: E=(0,+1), SE=(-1,+1) -> angle = 2pi - r
    facets = [
        ((0, 1), (1, 1), 0.0, 1.0),
        ((1, 0), (1, 1), 0.5 * np.pi, -1.0),
        ((1, 0), (1, -1), 0.5 * np.pi, 1.0),
        ((0, -1), (1, -1), np.pi, -1.0),
        ((0, -1), (-1, -1), np.pi, 1.0),
        ((-1, 0), (-1, -1), 1.5 * np.pi, -1.0),
        ((-1, 0), (-1, 1), 1.5 * np.pi, 1.0),
        ((0, 1), (-1, 1), 2.0 * np.pi, -1.0),
    ]
    z_c = z[1:-1, 1:-1]
    best_s = np.full_like(z_c, -1.0)
    best_ang = np.full_like(z_c, np.nan)
    pi4 = 0.25 * np.pi

    for (dr1, dc1), (dr2, dc2), base_ang, sign in facets:
        z1 = z[1 + dr1 : ny - 1 + dr1, 1 + dc1 : nx - 1 + dc1]
        z2 = z[1 + dr2 : ny - 1 + dr2, 1 + dc2 : nx - 1 + dc2]
        s1 = (z_c - z1) / dx
        s2 = (z1 - z2) / dx
        r = np.arctan2(s2, s1)
        # Clamp r to [0, pi/4] per Tarboton (1997)
        r_clamped = np.where(r < 0.0, 0.0, np.where(r > pi4, pi4, r))
        s = np.where(
            r < 0.0,
            s1,
            np.where(r > pi4, (z_c - z2) / (math.sqrt(2.0) * dx), np.hypot(s1, s2)),
        )
        # Handle s1 <= 0 & s2 <= 0 appropriately (negative s rejected when s_max > 0)
        valid = s > best_s
        best_s = np.where(valid, s, best_s)
        ang = (base_ang + sign * r_clamped) % (2.0 * np.pi)
        best_ang = np.where(valid, ang, best_ang)

    out = np.full_like(z, np.nan)
    out[1:-1, 1:-1] = best_ang
    return out


# ---------------------------------------------------------------------------
# Public Oracle Runners
# ---------------------------------------------------------------------------

def _rel_err(pred: np.ndarray, ref: np.ndarray) -> float:
    denom = np.maximum(np.abs(ref), 1e-6)
    return float(np.mean(np.abs(pred - ref) / denom))


def _angular_err_deg(pred_rad: np.ndarray, expected_rad: float) -> np.ndarray:
    diff = (np.degrees(pred_rad - expected_rad) + 180.0) % 360.0 - 180.0
    return np.abs(diff)


def run_self_test() -> dict[str, Any]:
    """Validate analytical closed-form formulas vs numerical quadrature and reference discrete grid."""
    dx = 0.5
    X, Y, _ = make_grid(extent_m=150.0, dx=dx)
    interior = (np.abs(X) <= 15.0) & (np.abs(Y) <= 15.0)
    pit_floor = (X * X + Y * Y) <= (1.25 * 1.25)

    # 1. Cross-check closed-form vs 4000-pt line quadrature on sample points
    pts_x = np.array([0.0, 2.5, -4.0, 6.0])
    pts_y = np.array([0.0, -3.5, 5.0, 1.5])
    a_parab = 0.015
    s_vtrench = 0.50
    R_pit, H_pit = 8.25, 0.90

    quad_checks = []
    for L in (10.0, 25.0, 50.0):
        # Paraboloid
        ep, es, ev = exact_paraboloid_openness_svf(pts_x, pts_y, a_parab, L, 16)
        qp, qs, qv = _quadrature_openness_svf(lambda xx, yy: a_parab * (xx**2 + yy**2), pts_x, pts_y, L, 16)
        err_p = max(_rel_err(ep, qp), _rel_err(es, qs), _rel_err(ev, qv))
        # V-trench
        ep2, es2, ev2 = exact_vtrench_openness_svf(pts_x, pts_y, s_vtrench, L, 16)
        qp2, qs2, qv2 = _quadrature_openness_svf(lambda xx, yy: s_vtrench * np.abs(xx), pts_x, pts_y, L, 16)
        err_v = max(_rel_err(ep2, qp2), _rel_err(es2, qs2), _rel_err(ev2, qv2))
        # Pit (test inside pit floor where r < R)
        px_in = np.array([0.0, 1.5, -2.0])
        py_in = np.array([0.0, -1.0, 1.5])
        ep3, es3, ev3 = exact_cylindrical_pit_openness_svf(px_in, py_in, R_pit, H_pit, L, 16)
        qp3, qs3, qv3 = _quadrature_openness_svf(
            lambda xx, yy: np.where(xx**2 + yy**2 < R_pit**2, -H_pit, 0.0), px_in, py_in, L, 16
        )
        err_c = max(_rel_err(ep3, qp3), _rel_err(es3, qs3), _rel_err(ev3, qv3))
        quad_checks.append({"L": L, "paraboloid_quad_err": err_p, "vtrench_quad_err": err_v, "pit_quad_err": err_c})
        assert err_p < 1e-4, f"Paraboloid closed-form vs quadrature mismatch: {err_p}"
        assert err_v < 1e-4, f"V-trench closed-form vs quadrature mismatch: {err_v}"
        assert err_c < 2e-3, f"Cylindrical pit closed-form vs quadrature mismatch: {err_c}"

    # 2. Cross-check discrete dx=0.5m raster reference vs closed-form (< 1%)
    dem_parab = (a_parab * (X**2 + Y**2)).astype(np.float32)
    dem_vtrench = (s_vtrench * np.abs(X)).astype(np.float32)
    dem_pit = np.where(X**2 + Y**2 < R_pit**2, -H_pit, 0.0).astype(np.float32)

    raster_checks = []
    for L in (10.0, 25.0, 50.0):
        for name, dem, exact_fn, mask in [
            ("paraboloid", dem_parab, lambda xx, yy: exact_paraboloid_openness_svf(xx, yy, a_parab, L, 16), interior),
            ("vtrench", dem_vtrench, lambda xx, yy: exact_vtrench_openness_svf(xx, yy, s_vtrench, L, 16), interior),
            ("cyl_pit", dem_pit, lambda xx, yy: exact_cylindrical_pit_openness_svf(xx, yy, R_pit, H_pit, L, 16), pit_floor),
        ]:
            rp, rs, rv = _reference_raster_openness_svf(dem, dx, L, 16)
            ep, es, ev = exact_fn(X, Y)
            e_phi = _rel_err(rp[mask], ep[mask])
            e_psi = _rel_err(rs[mask], es[mask])
            e_svf = _rel_err(rv[mask], ev[mask])
            raster_checks.append({"surface": name, "L": L, "phi_err": e_phi, "psi_err": e_psi, "svf_err": e_svf})
            assert max(e_phi, e_psi, e_svf) < 0.01, f"Reference raster error >=1% on {name} L={L}: {(e_phi, e_psi, e_svf)}"

    # 3. Tarboton D-inf reference check across non-cardinal, non-diagonal angles
    angles_deg = [17.0, 63.0, 128.0, 197.0, 215.0, 284.0, 311.0]
    Xp, Yp, _ = make_grid(extent_m=40.0, dx=dx)
    dinf_max_err = 0.0
    for deg in angles_deg:
        rad = math.radians(deg)
        dem_plane = (-0.25 * math.cos(rad) * Xp - 0.25 * math.sin(rad) * Yp + 100.0).astype(np.float64)
        pred = _reference_dinf_plane_test(dem_plane, dx)
        err = _angular_err_deg(pred[3:-3, 3:-3], rad)
        max_e = float(np.max(err))
        dinf_max_err = max(dinf_max_err, max_e)
        assert max_e < 0.5, f"Reference D-inf error {max_e} >= 0.5 deg at {deg} deg"

    return {
        "status": "PASS",
        "quadrature_checks": quad_checks,
        "raster_checks": raster_checks,
        "dinf_max_err_deg": dinf_max_err,
    }


def run_tier1_analytical() -> dict[str, Any]:
    """Run Tier-1 Analytical Oracles against live `palimpsest.derivatives`."""
    from palimpsest.derivatives import compute_dinf_flow, compute_openness, compute_svf

    dx = 0.5
    X, Y, _ = make_grid(extent_m=150.0, dx=dx)
    interior = (np.abs(X) <= 15.0) & (np.abs(Y) <= 15.0)
    pit_floor = (X * X + Y * Y) <= (1.25 * 1.25)

    a_parab = 0.015
    s_vtrench = 0.50
    R_pit, H_pit = 8.25, 0.90

    dem_parab = (a_parab * (X**2 + Y**2)).astype(np.float32)
    dem_vtrench = (s_vtrench * np.abs(X)).astype(np.float32)
    dem_pit = np.where(X**2 + Y**2 < R_pit**2, -H_pit, 0.0).astype(np.float32)

    openness_svf_results = []
    all_passed = True

    for L in (10.0, 25.0, 50.0):
        for name, dem, exact_fn, mask in [
            ("paraboloid", dem_parab, lambda xx, yy: exact_paraboloid_openness_svf(xx, yy, a_parab, L, 16), interior),
            ("vtrench", dem_vtrench, lambda xx, yy: exact_vtrench_openness_svf(xx, yy, s_vtrench, L, 16), interior),
            ("cyl_pit", dem_pit, lambda xx, yy: exact_cylindrical_pit_openness_svf(xx, yy, R_pit, H_pit, L, 16), pit_floor),
        ]:
            phi_pred, psi_pred, _ = compute_openness(dem, dx, L, n_azimuths=16)
            svf_pred = compute_svf(dem, dx, L=L, n_azimuths=16)
            phi_ex, psi_ex, svf_ex = exact_fn(X, Y)

            e_phi = _rel_err(phi_pred[mask], phi_ex[mask])
            e_psi = _rel_err(psi_pred[mask], psi_ex[mask])
            e_svf = _rel_err(svf_pred[mask], svf_ex[mask])
            passed = (e_phi < 0.01) and (e_psi < 0.01) and (e_svf < 0.01)
            if not passed:
                all_passed = False
            openness_svf_results.append({
                "surface": name,
                "L_m": L,
                "phi_rel_err": e_phi,
                "psi_rel_err": e_psi,
                "svf_rel_err": e_svf,
                "pass": passed,
            })

    # Tarboton D-inf across non-cardinal, non-diagonal angles
    angles_deg = [17.0, 63.0, 128.0, 197.0, 215.0, 284.0, 311.0]
    Xp, Yp, _ = make_grid(extent_m=50.0, dx=dx)
    dinf_results = []
    for deg in angles_deg:
        rad = math.radians(deg)
        slope_mag = 0.25
        dem_plane = (-slope_mag * math.cos(rad) * Xp - slope_mag * math.sin(rad) * Yp + 100.0).astype(np.float32)
        flow_ang, _, slope_rad = compute_dinf_flow(dem_plane, dx, fill_pits=False)
        err_deg = _angular_err_deg(flow_ang[4:-4, 4:-4], rad)
        mean_err = float(np.mean(err_deg))
        max_err = float(np.max(err_deg))
        expected_slope_deg = math.degrees(math.atan(slope_mag))
        slope_err_deg = float(np.mean(np.abs(np.degrees(slope_rad[4:-4, 4:-4]) - expected_slope_deg)))
        passed = (mean_err < 0.5) and (max_err < 0.5)
        if not passed:
            all_passed = False
        dinf_results.append({
            "target_deg": deg,
            "mean_angular_err_deg": mean_err,
            "max_angular_err_deg": max_err,
            "slope_err_deg": slope_err_deg,
            "pass": passed,
        })

    return {
        "oracle": "tier1_analytical",
        "status": "PASS" if all_passed else "FAIL",
        "openness_and_svf": openness_svf_results,
        "dinf_flow_azimuth": dinf_results,
    }
