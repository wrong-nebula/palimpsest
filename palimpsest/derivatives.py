"""First-principles terrain derivatives, Tarboton (1997) D-infinity flow, and BH-FDR."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy.ndimage import distance_transform_edt, gaussian_filter, maximum_filter, uniform_filter


@dataclass
class DerivativeBundle:
    phi_10: np.ndarray            # float32 (ny, nx), positive openness L=10m (rad)
    psi_10: np.ndarray            # float32 (ny, nx), negative openness L=10m (rad)
    I_10: np.ndarray              # float32 (ny, nx), differential openness (phi-psi)/2 (rad)
    phi_25: np.ndarray            # float32 (ny, nx), L=25m (rad)
    psi_25: np.ndarray            # float32 (ny, nx), L=25m (rad)
    I_25: np.ndarray              # float32 (ny, nx), L=25m (rad)
    phi_50: np.ndarray            # float32 (ny, nx), L=50m (rad)
    psi_50: np.ndarray            # float32 (ny, nx), L=50m (rad)
    I_50: np.ndarray              # float32 (ny, nx), L=50m (rad)
    svf: np.ndarray               # float32 (ny, nx), Sky-View Factor in [0, 1]
    lrm: np.ndarray               # float32 (ny, nx), Hesse Local Relief Model (m)
    rrim_rgb: np.ndarray          # uint8 (ny, nx, 3), Chiba RRIM RGB
    vat_rgb: np.ndarray           # uint8 (ny, nx, 3), Kokalj & Somrak VAT RGB
    flow_angle_rad: np.ndarray    # float32 (ny, nx), Tarboton D-inf angle (rad, CCW from +East)
    upslope_area_m2: np.ndarray   # float32 (ny, nx), Tarboton D-inf contributing area (m^2)
    slope_rad: np.ndarray         # float32 (ny, nx), local slope arctan(|grad z|) (rad)
    drainage_violation: np.ndarray  # float32 (ny, nx), normalized violation score in [0, 1]


def _ray_steps(L: float, dx: float, large_grid: bool) -> np.ndarray:
    n_base = max(1, int(math.floor(L / dx)))
    if not large_grid or L <= 10.0 + 1e-6:
        return np.arange(1, n_base + 1, dtype=np.float64) * dx
    s1 = np.arange(1, min(n_base, int(round(10.0 / dx))) + 1, dtype=np.float64) * dx
    parts = [s1]
    if L > 10.0 + 1e-6:
        s2_end = min(n_base, int(round(25.0 / dx)))
        s2 = np.arange(int(round(10.0 / dx)) + 3, s2_end + 1, 3, dtype=np.float64) * dx
        if s2.size > 0:
            parts.append(s2)
        if s2_end > int(round(10.0 / dx)) and (s2.size == 0 or s2[-1] < min(L, 25.0) - 1e-6):
            parts.append(np.array([min(L, 25.0)], dtype=np.float64))
    if L > 25.0 + 1e-6:
        s3 = np.arange(int(round(25.0 / dx)) + 5, n_base + 1, 5, dtype=np.float64) * dx
        if s3.size > 0:
            parts.append(s3)
        if s3.size == 0 or s3[-1] < L - 1e-6:
            parts.append(np.array([L], dtype=np.float64))
    return np.unique(np.concatenate(parts))


def _openness_and_svf_core(
    dem: np.ndarray,
    dx: float,
    L_values: list[float],
    n_azimuths: int = 16,
    compute_svf_at_L: float | None = None,
) -> tuple[dict[float, tuple[np.ndarray, np.ndarray, np.ndarray]], np.ndarray | None]:
    """Compute multi-scale Yokoyama openness (and optional Zaksek SVF) in one radial pass."""
    dem32 = np.ascontiguousarray(dem, dtype=np.float32)
    ny, nx = dem32.shape
    L_sorted = sorted(float(L) for L in L_values)
    L_max = L_sorted[-1]
    large_grid = (ny * nx) > 2_500_000

    steps = _ray_steps(L_max, dx, large_grid=large_grid)
    # Identify indices where each requested L finishes
    checkpoints: dict[int, list[float]] = {}
    for L_val in L_sorted:
        idx = int(np.searchsorted(steps, L_val + 1e-6, side="right")) - 1
        idx = max(0, min(len(steps) - 1, idx))
        checkpoints.setdefault(idx, []).append(L_val)

    angles = 2.0 * math.pi * np.arange(n_azimuths, dtype=np.float64) / float(n_azimuths)
    half_pi = np.float32(math.pi / 2.0)

    phi_acc = {L_val: np.zeros((ny, nx), dtype=np.float32) for L_val in L_sorted}
    psi_acc = {L_val: np.zeros((ny, nx), dtype=np.float32) for L_val in L_sorted}
    svf_acc = np.zeros((ny, nx), dtype=np.float32) if compute_svf_at_L is not None else None

    strip_h = 128 if large_grid else min(256, ny)
    buf1 = np.empty((strip_h, nx), dtype=np.float32)
    buf2 = np.empty((strip_h, nx), dtype=np.float32)
    buf3 = np.empty((strip_h, nx), dtype=np.float32)
    mup = np.empty((strip_h, nx), dtype=np.float32)
    mdn = np.empty((strip_h, nx), dtype=np.float32)

    use_bilinear = not large_grid

    for r0 in range(0, ny, strip_h):
        r1 = min(ny, r0 + strip_h)
        sh = r1 - r0
        z0 = dem32[r0:r1]
        mup_v = mup[:sh]
        mdn_v = mdn[:sh]
        b1_v = buf1[:sh]
        b2_v = buf2[:sh]
        b3_v = buf3[:sh]

        for ak in angles:
            ca, sa = math.cos(ak), math.sin(ak)
            mup_v.fill(-np.inf)
            mdn_v.fill(-np.inf)
            seen_steps = set()

            for idx_s, d in enumerate(steps):
                if use_bilinear:
                    dr = (d / dx) * sa
                    dc = (d / dx) * ca
                    idr = math.floor(dr)
                    idc = math.floor(dc)
                    fr = np.float32(dr - idr)
                    fc = np.float32(dc - idc)
                    omfc = np.float32(1.0) - fc
                    omfr = np.float32(1.0) - fr
                    inv_d = np.float32(1.0 / d)

                    rs = max(0, -(r0 + idr))
                    re = min(sh, ny - 1 - (r0 + idr))
                    cs = max(0, -idc)
                    ce = min(nx, nx - 1 - idc)
                    if rs < re and cs < ce:
                        vh, vw = re - rs, ce - cs
                        sr0, sr1 = r0 + rs + idr, r0 + re + idr
                        sc0, sc1 = cs + idc, ce + idc
                        t = b1_v[:vh, :vw]
                        bt = b2_v[:vh, :vw]
                        w = b3_v[:vh, :vw]
                        np.multiply(dem32[sr0:sr1, sc0:sc1], omfc, out=t)
                        np.multiply(dem32[sr0:sr1, sc0 + 1:sc1 + 1], fc, out=w)
                        np.add(t, w, out=t)
                        np.multiply(dem32[sr0 + 1:sr1 + 1, sc0:sc1], omfc, out=bt)
                        np.multiply(dem32[sr0 + 1:sr1 + 1, sc0 + 1:sc1 + 1], fc, out=w)
                        np.add(bt, w, out=bt)
                        np.multiply(t, omfr, out=t)
                        np.multiply(bt, fr, out=bt)
                        np.add(t, bt, out=t)
                        np.subtract(t, z0[rs:re, cs:ce], out=t)
                        np.multiply(t, inv_d, out=t)
                        np.maximum(mup_v[rs:re, cs:ce], t, out=mup_v[rs:re, cs:ce])
                        np.negative(t, out=t)
                        np.maximum(mdn_v[rs:re, cs:ce], t, out=mdn_v[rs:re, cs:ce])
                else:
                    idr = round((d / dx) * sa)
                    idc = round((d / dx) * ca)
                    if (idr, idc) not in seen_steps:
                        seen_steps.add((idr, idc))
                        dist = math.hypot(idr * dx, idc * dx)
                        if dist > 0.0:
                            inv_d = np.float32(1.0 / dist)
                            rs = max(0, -(r0 + idr))
                            re = min(sh, ny - (r0 + idr))
                            cs = max(0, -idc)
                            ce = min(nx, nx - idc)
                            if rs < re and cs < ce:
                                t = b1_v[:re - rs, :ce - cs]
                                np.subtract(
                                    dem32[r0 + rs + idr:r0 + re + idr, cs + idc:ce + idc],
                                    z0[rs:re, cs:ce],
                                    out=t,
                                )
                                np.multiply(t, inv_d, out=t)
                                np.maximum(mup_v[rs:re, cs:ce], t, out=mup_v[rs:re, cs:ce])
                                np.negative(t, out=t)
                                np.maximum(mdn_v[rs:re, cs:ce], t, out=mdn_v[rs:re, cs:ce])

                if idx_s in checkpoints:
                    for L_val in checkpoints[idx_s]:
                        np.copyto(b1_v, mup_v)
                        b1_v[~np.isfinite(b1_v)] = np.float32(0.0)
                        np.arctan(b1_v, out=b1_v)
                        if svf_acc is not None and abs(L_val - float(compute_svf_at_L)) < 1e-6:
                            np.maximum(b1_v, np.float32(0.0), out=b2_v)
                            np.sin(b2_v, out=b2_v)
                            svf_acc[r0:r1] += b2_v
                        np.subtract(half_pi, b1_v, out=b1_v)
                        phi_acc[L_val][r0:r1] += b1_v

                        np.copyto(b1_v, mdn_v)
                        b1_v[~np.isfinite(b1_v)] = np.float32(0.0)
                        np.arctan(b1_v, out=b1_v)
                        np.subtract(half_pi, b1_v, out=b1_v)
                        psi_acc[L_val][r0:r1] += b1_v

    inv_n = np.float32(1.0 / float(n_azimuths))
    out: dict[float, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
    for L_val in L_sorted:
        phi = (phi_acc[L_val] * inv_n).astype(np.float32, copy=False)
        psi = (psi_acc[L_val] * inv_n).astype(np.float32, copy=False)
        diff_I = (np.float32(0.5) * (phi - psi)).astype(np.float32, copy=False)
        out[L_val] = (phi, psi, diff_I)

    svf_out = None
    if svf_acc is not None:
        svf_out = np.clip(np.float32(1.0) - svf_acc * inv_n, 0.0, 1.0).astype(np.float32)

    return out, svf_out


def compute_openness(
    dem: np.ndarray,
    dx: float,
    L: float,
    n_azimuths: int = 16,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Yokoyama et al. (2002) openness. Returns (phi_rad, psi_rad, diff_I_rad)."""
    res, _ = _openness_and_svf_core(dem, dx=float(dx), L_values=[float(L)], n_azimuths=int(n_azimuths))
    return res[float(L)]


def compute_svf(
    dem: np.ndarray,
    dx: float,
    L: float = 10.0,
    n_azimuths: int = 16,
) -> np.ndarray:
    """Zaksek et al. (2011) Sky-View Factor in [0, 1]."""
    _, svf = _openness_and_svf_core(
        dem,
        dx=float(dx),
        L_values=[float(L)],
        n_azimuths=int(n_azimuths),
        compute_svf_at_L=float(L),
    )
    assert svf is not None
    return svf


def _compute_slope_rad(dem: np.ndarray, dx: float) -> np.ndarray:
    grad_y, grad_x = np.gradient(dem.astype(np.float32, copy=False), np.float32(dx))
    return np.arctan(np.hypot(grad_x, grad_y)).astype(np.float32)


def _rrim_from_arrays(
    slope_rad: np.ndarray,
    I_rad: np.ndarray,
    slope_max_deg: float = 45.0,
    I_clip_rad: float = 0.5,
) -> np.ndarray:
    s_norm = np.clip(slope_rad / np.float32(math.radians(slope_max_deg)), 0.0, 1.0)
    v_norm = np.clip((I_rad + np.float32(I_clip_rad)) / np.float32(2.0 * I_clip_rad), 0.0, 1.0)
    r = v_norm
    g = v_norm * (np.float32(1.0) - s_norm)
    b = g
    rgb = np.stack((r, g, b), axis=-1)
    return np.clip(np.rint(rgb * 255.0), 0, 255).astype(np.uint8)


def compute_rrim(
    dem: np.ndarray,
    dx: float,
    L: float = 10.0,
    n_azimuths: int = 16,
    slope_max_deg: float = 45.0,
    I_clip_rad: float = 0.5,
) -> np.ndarray:
    """Chiba et al. (2008) Red Relief Image Map. Returns uint8 (ny, nx, 3)."""
    _, _, I_rad = compute_openness(dem, dx=dx, L=L, n_azimuths=n_azimuths)
    slope_rad = _compute_slope_rad(dem, dx=dx)
    return _rrim_from_arrays(slope_rad, I_rad, slope_max_deg=slope_max_deg, I_clip_rad=I_clip_rad)


def _odd_reflect_pad(arr: np.ndarray, pw: int) -> np.ndarray:
    """Odd-reflection padding preserves linear slopes exactly at boundaries."""
    ny, nx = arr.shape
    pr = min(pw, max(0, ny - 2))
    pc = min(pw, max(0, nx - 2))
    if pr > 0:
        top = np.float32(2.0) * arr[0:1, :] - arr[pr:0:-1, :]
        bot = np.float32(2.0) * arr[-1:, :] - arr[-2:-2 - pr:-1, :]
        v = np.vstack((top, arr, bot))
    else:
        v = arr
    if pc > 0:
        left = np.float32(2.0) * v[:, 0:1] - v[:, pc:0:-1]
        right = np.float32(2.0) * v[:, -1:] - v[:, -2:-2 - pc:-1]
        return np.hstack((left, v, right))
    return v


def compute_lrm(
    dem: np.ndarray,
    dx: float,
    radius_m: float = 15.0,
) -> np.ndarray:
    """Hesse (2010) Local Relief Model in meters.

    1. Smooth DEM with odd-padded low-pass filter of scale radius_m.
    2. Detect zero-crossing contours of (dem - z_smooth).
    3. Re-interpolate purged harmonic background surface across local anomalies
       from zero-crossing breaklines so amplitudes are preserved without halos.
    """
    dem32 = np.asarray(dem, dtype=np.float32)
    ny, nx = dem32.shape
    sigma_px = max(1.0, (0.5 * float(radius_m)) / float(dx))
    pad_w = int(round(3.0 * sigma_px))
    dem_p = _odd_reflect_pad(dem32, pad_w)
    pr = min(pad_w, max(0, ny - 2))
    pc = min(pad_w, max(0, nx - 2))
    z_smooth = gaussian_filter(dem_p, sigma=sigma_px, mode="nearest")[pr:pr + ny, pc:pc + nx].astype(np.float32)
    d0 = dem32 - z_smooth

    zero_cross = np.zeros(dem32.shape, dtype=bool)
    zero_cross[:-1, :] |= (d0[:-1, :] * d0[1:, :]) <= 0.0
    zero_cross[1:, :] |= (d0[:-1, :] * d0[1:, :]) <= 0.0
    zero_cross[:, :-1] |= (d0[:, :-1] * d0[:, 1:]) <= 0.0
    zero_cross[:, 1:] |= (d0[:, :-1] * d0[:, 1:]) <= 0.0
    zero_cross |= np.abs(d0) < np.float32(0.02)

    if not np.any(zero_cross) or np.all(zero_cross):
        return d0.astype(np.float32)

    dist_px, idx = distance_transform_edt(~zero_cross, return_indices=True)
    z_bg = dem32[idx[0], idx[1]].copy()
    # Blend distant (> radius_m) boundary gaps smoothly toward z_smooth
    far_w = np.clip((dist_px * float(dx)) / max(float(radius_m), 1.0), 0.0, 1.0).astype(np.float32)
    z_bg = (np.float32(1.0) - far_w) * z_bg + far_w * z_smooth

    free = ~zero_cross
    n_iter = 20 if (ny * nx) > 2_500_000 else 40
    pad = np.pad(z_bg, 1, mode="edge")
    for _ in range(n_iter):
        avg = np.float32(0.25) * (
            pad[:-2, 1:-1] + pad[2:, 1:-1] + pad[1:-1, :-2] + pad[1:-1, 2:]
        )
        pad[1:-1, 1:-1][free] = avg[free]
    z_purged = pad[1:-1, 1:-1]

    return (dem32 - z_purged).astype(np.float32)


def _vat_from_arrays(
    dem: np.ndarray,
    dx: float,
    phi: np.ndarray,
    svf: np.ndarray,
    slope_rad: np.ndarray,
) -> np.ndarray:
    grad_y, grad_x = np.gradient(dem.astype(np.float32, copy=False), np.float32(dx))
    norm = np.sqrt(grad_x * grad_x + grad_y * grad_y + np.float32(1.0))
    nx_surf = -grad_x / norm
    ny_surf = -grad_y / norm
    nz_surf = np.float32(1.0) / norm

    # 315 deg CW from North (NW), 35 deg elevation
    elev = math.radians(35.0)
    az = math.radians(315.0)
    sx = np.float32(math.cos(elev) * math.sin(az))
    sy = np.float32(math.cos(elev) * math.cos(az))
    sz = np.float32(math.sin(elev))
    hs = np.clip(nx_surf * sx + ny_surf * sy + nz_surf * sz, 0.0, 1.0)

    # Inverted slope gradient
    slope_inv = np.float32(1.0) - np.clip(slope_rad / np.float32(math.radians(45.0)), 0.0, 1.0)
    base = np.float32(0.55) * hs + np.float32(0.45) * slope_inv

    # Positive openness overlay / soft-light
    phi_norm = np.clip((phi - np.float32(1.05)) / np.float32(1.65 - 1.05), 0.0, 1.0)
    overlay = np.where(
        base < 0.5,
        np.float32(2.0) * base * phi_norm,
        np.float32(1.0) - np.float32(2.0) * (np.float32(1.0) - base) * (np.float32(1.0) - phi_norm),
    )
    blended = np.float32(0.5) * base + np.float32(0.5) * overlay

    # SVF multiply
    svf_stretch = np.clip((svf - np.float32(0.3)) / np.float32(0.7), 0.0, 1.0)
    vat = np.clip(blended * (np.float32(0.3) + np.float32(0.7) * svf_stretch), 0.0, 1.0)
    u8 = np.clip(np.rint(vat * 255.0), 0, 255).astype(np.uint8)
    return np.stack((u8, u8, u8), axis=-1)


def compute_vat(
    dem: np.ndarray,
    dx: float,
    L: float = 10.0,
    n_azimuths: int = 16,
) -> np.ndarray:
    """Kokalj & Somrak (2019) VAT RGB composite. Returns uint8 (ny, nx, 3)."""
    res, svf = _openness_and_svf_core(
        dem, dx=float(dx), L_values=[float(L)], n_azimuths=int(n_azimuths), compute_svf_at_L=float(L)
    )
    assert svf is not None
    phi, _, _ = res[float(L)]
    slope_rad = _compute_slope_rad(dem, dx=dx)
    return _vat_from_arrays(dem, dx=dx, phi=phi, svf=svf, slope_rad=slope_rad)


def _fill_depressions(dem: np.ndarray) -> np.ndarray:
    """Simple priority-flood depression filling (Barnes et al. 2014) for optional fill_pits=True."""
    import heapq

    ny, nx = dem.shape
    out = dem.astype(np.float64, copy=True)
    visited = np.zeros((ny, nx), dtype=bool)
    pq: list[tuple[float, int, int]] = []

    for r in range(ny):
        for c in (0, nx - 1):
            if not visited[r, c]:
                visited[r, c] = True
                heapq.heappush(pq, (float(out[r, c]), r, c))
    for c in range(1, nx - 1):
        for r in (0, ny - 1):
            if not visited[r, c]:
                visited[r, c] = True
                heapq.heappush(pq, (float(out[r, c]), r, c))

    nbrs = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
    eps = 1e-6
    while pq:
        z, r, c = heapq.heappop(pq)
        for dr, dc in nbrs:
            nr, nc = r + dr, c + dc
            if 0 <= nr < ny and 0 <= nc < nx and not visited[nr, nc]:
                visited[nr, nc] = True
                if out[nr, nc] <= z:
                    out[nr, nc] = z + eps
                heapq.heappush(pq, (float(out[nr, nc]), nr, nc))
    return out.astype(np.float32)


def compute_dinf_flow(
    dem: np.ndarray,
    dx: float,
    fill_pits: bool = False,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Tarboton (1997) D-infinity flow.
    Returns (flow_angle_rad, upslope_area_m2, slope_rad).
    Angle convention: CCW from +East in [0, 2*pi).
    """
    z = _fill_depressions(dem) if fill_pits else np.asarray(dem, dtype=np.float32)
    ny, nx = z.shape
    N = ny * nx

    # Pad with +inf outside domain so out-of-bounds facets never win
    pad_z = np.pad(z, 1, mode="constant", constant_values=np.float32(np.inf))

    # 8 Tarboton planar facets in (row=S->N, col=W->E) coordinates:
    # (dr1, dc1, dr2, dc2, base_angle, sign)
    facets = [
        (0, 1, 1, 1, 0.0, 1.0),
        (1, 0, 1, 1, math.pi / 2.0, -1.0),
        (1, 0, 1, -1, math.pi / 2.0, 1.0),
        (0, -1, 1, -1, math.pi, -1.0),
        (0, -1, -1, -1, math.pi, 1.0),
        (-1, 0, -1, -1, 1.5 * math.pi, -1.0),
        (-1, 0, -1, 1, 1.5 * math.pi, 1.0),
        (0, 1, -1, 1, 2.0 * math.pi, -1.0),
    ]

    best_s = np.zeros((ny, nx), dtype=np.float32)
    best_ang = np.zeros((ny, nx), dtype=np.float32)
    best_r = np.zeros((ny, nx), dtype=np.float32)
    best_f = np.full((ny, nx), -1, dtype=np.int8)

    inv_dx = np.float32(1.0 / float(dx))
    inv_dd = np.float32(1.0 / (math.sqrt(2.0) * float(dx)))
    q_pi = np.float32(math.pi / 4.0)

    for f_idx, (dr1, dc1, dr2, dc2, base, sgn) in enumerate(facets):
        z1 = pad_z[1 + dr1:1 + dr1 + ny, 1 + dc1:1 + dc1 + nx]
        z2 = pad_z[1 + dr2:1 + dr2 + ny, 1 + dc2:1 + dc2 + nx]

        # When z1 is +inf (outside domain), facet cannot carry valid downslope flow
        z1_fin = np.isfinite(z1)
        z2_fin = np.isfinite(z2)
        z1_safe = np.where(z1_fin, z1, z)
        z2_safe = np.where(z2_fin, z2, z)

        s1 = np.where(z1_fin, (z - z1_safe) * inv_dx, np.float32(-np.inf))
        s2 = np.where(z1_fin & z2_fin, (z1_safe - z2_safe) * inv_dx, np.float32(0.0))

        r = np.arctan2(s2, s1)
        s = np.hypot(s1, s2)

        mask_lo = r < np.float32(0.0)
        r = np.where(mask_lo, np.float32(0.0), r)
        s = np.where(mask_lo, s1, s)

        mask_hi = r > q_pi
        r = np.where(mask_hi, q_pi, r)
        s_diag = np.where(z2_fin, (z - z2_safe) * inv_dd, np.float32(-np.inf))
        s = np.where(mask_hi, s_diag, s)

        # Require both target cells used (or diagonal when r==pi/4, cardinal when r==0) to be finite
        valid_f = np.where(r <= np.float32(1e-6), z1_fin, np.where(r >= q_pi - np.float32(1e-6), z2_fin, z1_fin & z2_fin))
        win = valid_f & (s > best_s)

        best_s = np.where(win, s, best_s)
        best_r = np.where(win, r, best_r)
        best_f = np.where(win, np.int8(f_idx), best_f)
        ang_f = np.mod(np.float32(base) + np.float32(sgn) * r, np.float32(2.0 * math.pi))
        best_ang = np.where(win, ang_f, best_ang)

    # Release facet work arrays before allocating the full drainage graph.
    del z1, z2, z1_safe, z2_safe, pad_z, z1_fin, z2_fin, s1, s2, r, s
    del mask_lo, mask_hi, s_diag, valid_f, win, ang_f

    # Topological upslope contributing area via Kahn's wavefront
    tgt1 = np.full(N, -1, dtype=np.int32)
    tgt2 = np.full(N, -1, dtype=np.int32)
    w1 = np.zeros(N, dtype=np.float32)
    w2 = np.zeros(N, dtype=np.float32)

    dr1_arr = np.array([f[0] for f in facets], dtype=np.int32)
    dc1_arr = np.array([f[1] for f in facets], dtype=np.int32)
    dr2_arr = np.array([f[2] for f in facets], dtype=np.int32)
    dc2_arr = np.array([f[3] for f in facets], dtype=np.int32)

    rows = np.arange(ny, dtype=np.int32)[:, None]
    cols = np.arange(nx, dtype=np.int32)[None, :]
    valid_cell = best_f >= 0
    f_safe = np.maximum(best_f, 0)

    nr1 = rows + dr1_arr[f_safe]
    nc1 = cols + dc1_arr[f_safe]
    nr2 = rows + dr2_arr[f_safe]
    nc2 = cols + dc2_arr[f_safe]

    ok1 = (valid_cell & (nr1 >= 0) & (nr1 < ny) & (nc1 >= 0) & (nc1 < nx)).ravel()
    ok2 = (valid_cell & (nr2 >= 0) & (nr2 < ny) & (nc2 >= 0) & (nc2 < nx)).ravel()

    ww2 = (best_r / q_pi).ravel()
    ww1 = np.float32(1.0) - ww2
    use1 = ok1 & (ww1 > np.float32(1e-6))
    use2 = ok2 & (ww2 > np.float32(1e-6))

    tgt1[use1] = nr1.ravel()[use1] * nx + nc1.ravel()[use1]
    tgt2[use2] = nr2.ravel()[use2] * nx + nc2.ravel()[use2]
    w1[use1] = ww1[use1]
    w2[use2] = ww2[use2]

    del nr1, nc1, nr2, nc2, ok1, ok2, ww1, ww2, best_r, f_safe, best_f, valid_cell
    in_deg = np.bincount(tgt1[use1], minlength=N) + np.bincount(tgt2[use2], minlength=N)
    area = np.full(N, float(dx * dx), dtype=np.float32)
    frontier = np.flatnonzero(in_deg == 0)

    while frontier.size > 0:
        t1_all = tgt1[frontier]
        t2_all = tgt2[frontier]
        m1 = t1_all >= 0
        m2 = t2_all >= 0
        t1_f = t1_all[m1]
        t2_f = t2_all[m2]
        if t1_f.size > 0:
            np.add.at(area, t1_f, area[frontier[m1]] * w1[frontier[m1]])
            np.subtract.at(in_deg, t1_f, 1)
        if t2_f.size > 0:
            np.add.at(area, t2_f, area[frontier[m2]] * w2[frontier[m2]])
            np.subtract.at(in_deg, t2_f, 1)
        if t1_f.size == 0 and t2_f.size == 0:
            break
        touched = np.unique(np.concatenate([t1_f, t2_f]))
        frontier = touched[in_deg[touched] == 0]

    slope_rad = np.arctan(best_s).astype(np.float32)
    return (
        best_ang.astype(np.float32),
        area.reshape((ny, nx)).astype(np.float32),
        slope_rad,
    )


def compute_drainage_violation(
    dem: np.ndarray,
    flow_angle_rad: np.ndarray,
    upslope_area_m2: np.ndarray,
    slope_rad: np.ndarray,
    dx: float,
) -> np.ndarray:
    """Returns drainage violation score in [0, 1] (float32).

    Combines:
    1. Flat-terrace violation: low local slope (< ~7 deg) embedded in a steep
       macro hillslope (> 16 deg) with sharp local flow deflection/contrast.
    2. Transverse ridge-cut (horikiri) violation: concave incision with near-zero
       upslope contributing area sitting on a convex macro ridge.
    """
    dem32 = np.asarray(dem, dtype=np.float32)
    # Macro hillslope trend (~15 m smoothing)
    sigma_macro = max(2.0, 12.0 / float(dx))
    z_macro = gaussian_filter(dem32, sigma=sigma_macro, mode="nearest")
    my, mx = np.gradient(z_macro, np.float32(dx))
    macro_slope_deg = np.rad2deg(np.arctan(np.hypot(mx, my)))
    macro_flow_ang = np.arctan2(-my, -mx)

    local_slope_deg = np.rad2deg(slope_rad)

    # 1) Flat terrace on steep macro hillslope
    flat_factor = np.clip((10.0 - local_slope_deg) / 7.0, 0.0, 1.0)
    steep_bg_factor = np.clip((macro_slope_deg - 14.0) / 14.0, 0.0, 1.0)

    # Flow deflection between local D-inf and macro slope direction
    ang_diff = np.abs(np.arctan2(np.sin(flow_angle_rad - macro_flow_ang), np.cos(flow_angle_rad - macro_flow_ang)))
    deflection_factor = np.clip(ang_diff / np.float32(math.pi / 2.0), 0.0, 1.0)

    # Scarp adjacency boost (local max slope within 6m)
    scarp_rad = max(2, int(round(6.0 / float(dx))))
    near_max_slope = maximum_filter(local_slope_deg, size=2 * scarp_rad + 1)
    scarp_boost = np.clip((near_max_slope - 20.0) / 18.0, 0.0, 1.0)

    terrace_viol = flat_factor * steep_bg_factor * (np.float32(0.5) + np.float32(0.5) * np.maximum(deflection_factor, scarp_boost))

    del my, mx, macro_slope_deg, macro_flow_ang, local_slope_deg
    del flat_factor, steep_bg_factor, ang_diff, deflection_factor, near_max_slope, scarp_boost

    # 2) Transverse dry ridge-cut (horikiri) / concave dry incision
    sigma_local = max(1.0, 4.0 / float(dx))
    z_loc = gaussian_filter(dem32, sigma=sigma_local, mode="nearest")
    # Positive local concavity (macro trend higher than local surface => incised)
    incision_depth = np.clip((z_macro - dem32) / np.float32(2.0), 0.0, 1.0)
    del z_macro
    # Local curvature concavity (Laplacian > 0 => concave)
    gy, gx = np.gradient(z_loc, np.float32(dx))
    gxx = np.gradient(gx, np.float32(dx), axis=1)
    gyy = np.gradient(gy, np.float32(dx), axis=0)
    del gx, gy, z_loc
    lap = gxx + gyy
    concave_factor = np.clip(lap / np.float32(0.15), 0.0, 1.0)

    # Dry (low upslope area A << fluvial threshold ~1500 m^2)
    dry_factor = np.exp(-upslope_area_m2 / np.float32(600.0)).astype(np.float32)

    incision_viol = incision_depth * concave_factor * dry_factor

    score = np.maximum(terrace_viol, incision_viol)
    return np.clip(score, 0.0, 1.0).astype(np.float32)


def benjamini_hochberg_fdr(
    p_values: np.ndarray,
    q: float = 0.05,
) -> tuple[np.ndarray, float]:
    """Benjamini & Hochberg (1995) step-up FDR control.
    Returns (rejected_mask_bool, p_cutoff).
    """
    p_arr = np.asarray(p_values, dtype=np.float64)
    rejected = np.zeros(p_arr.shape, dtype=bool)
    finite_mask = np.isfinite(p_arr)
    p_fin = p_arr[finite_mask]
    m = p_fin.size
    if m == 0:
        return rejected, 0.0

    order = np.argsort(p_fin, kind="mergesort")
    p_sorted = p_fin[order]
    ranks = np.arange(1, m + 1, dtype=np.float64)
    thresholds = (ranks / float(m)) * float(q)
    passing = np.flatnonzero(p_sorted <= thresholds)
    if passing.size == 0:
        return rejected, 0.0

    k_star = int(passing[-1])
    p_cutoff = float(p_sorted[k_star])
    rejected = finite_mask & (p_arr <= p_cutoff)
    return rejected, p_cutoff


def compute_bh_qvalues(p_values: np.ndarray) -> np.ndarray:
    """Compute Benjamini-Hochberg adjusted q-values via monotone step-up clamping."""
    p_arr = np.asarray(p_values, dtype=np.float64)
    out = np.ones_like(p_arr, dtype=np.float64)
    flat = p_arr.ravel()
    fin = np.isfinite(flat)
    m = int(np.count_nonzero(fin))
    if m == 0:
        return out
    p_fin = flat[fin]
    order = np.argsort(p_fin, kind="mergesort")
    p_sorted = p_fin[order]
    ranks = np.arange(1, m + 1, dtype=np.float64)
    raw_q = np.minimum(1.0, (float(m) / ranks) * p_sorted)
    q_sorted = np.minimum.accumulate(raw_q[::-1])[::-1]
    q_fin = np.empty_like(p_fin)
    q_fin[order] = q_sorted
    out_flat = out.ravel()
    out_flat[fin] = q_fin
    return out


def compute_all_derivatives(
    dtm: np.ndarray,
    dx: float = 0.5,
    n_azimuths: int = 16,
    fill_pits: bool = False,
) -> DerivativeBundle:
    """Compute the full DerivativeBundle cleanly in one coordinated pass."""
    openness_map, svf = _openness_and_svf_core(
        dtm,
        dx=float(dx),
        L_values=[10.0, 25.0, 50.0],
        n_azimuths=int(n_azimuths),
        compute_svf_at_L=10.0,
    )
    assert svf is not None
    phi_10, psi_10, I_10 = openness_map[10.0]
    phi_25, psi_25, I_25 = openness_map[25.0]
    phi_50, psi_50, I_50 = openness_map[50.0]

    flow_angle_rad, upslope_area_m2, dinf_slope_rad = compute_dinf_flow(
        dtm, dx=float(dx), fill_pits=fill_pits
    )
    grad_slope_rad = _compute_slope_rad(dtm, dx=float(dx))
    lrm = compute_lrm(dtm, dx=float(dx), radius_m=15.0)
    rrim_rgb = _rrim_from_arrays(grad_slope_rad, I_10)
    vat_rgb = _vat_from_arrays(dtm, dx=float(dx), phi=phi_10, svf=svf, slope_rad=grad_slope_rad)
    drainage_violation = compute_drainage_violation(
        dtm, flow_angle_rad=flow_angle_rad, upslope_area_m2=upslope_area_m2, slope_rad=grad_slope_rad, dx=float(dx)
    )

    return DerivativeBundle(
        phi_10=phi_10,
        psi_10=psi_10,
        I_10=I_10,
        phi_25=phi_25,
        psi_25=psi_25,
        I_25=I_25,
        phi_50=phi_50,
        psi_50=psi_50,
        I_50=I_50,
        svf=svf,
        lrm=lrm,
        rrim_rgb=rrim_rgb,
        vat_rgb=vat_rgb,
        flow_angle_rad=flow_angle_rad,
        upslope_area_m2=upslope_area_m2,
        slope_rad=grad_slope_rad,
        drainage_violation=drainage_violation,
    )
