"""Local earthwork tests against a quadratic hillslope using metre-scale samples."""

import math
from functools import lru_cache

import numpy as np
from scipy.ndimage import binary_closing, binary_dilation, find_objects, gaussian_filter, label, maximum_filter
from scipy.linalg import lstsq
from scipy.stats import f


def _fit(design, elevations):
    """Pivoted QR handles sparse, asymmetric footprints without normal equations."""
    return lstsq(design, elevations, lapack_driver="gelsy", check_finite=False)[0]


@lru_cache(maxsize=64)
def _window(radius, step):
    n = math.ceil(radius / step)
    y, x = np.mgrid[-n:n+1, -n:n+1] * step / radius
    disk = x*x + y*y <= 1
    u, v = x[disk], y[disk]
    design = np.stack([np.ones_like(u), u, v, u*u, u*v, v*v], axis=1)
    return n, disk, u, v, design


def _profile(z, supported, row, col, step, kind, scale, angle, offsets=None):
    """Fit a smooth background and a compact alternative on the same support."""
    radius = scale * (4.5 if kind == "horikiri" else 2.5)
    n, disk, u, v, poly = _window(radius, step)
    if min(row, col, z.shape[0]-1-row, z.shape[1]-1-col) < n:
        return
    box = np.s_[row-n:row+n+1, col-n:col+n+1]
    valid = supported[box][disk]
    if offsets is not None:
        off_y, off_x = offsets
        u = u + (off_x[box][disk] - off_x[row, col])/radius
        v = v + (off_y[box][disk] - off_y[row, col])/radius
        poly = np.column_stack([np.ones_like(u), u, v, u*u, u*v, v*v])
    r = np.hypot(u, v) * radius / scale
    core = r <= 0.6
    if not core.any() or valid.mean() < 0.30 or valid[core].mean() < 0.50:
        return
    h = z[box][disk][valid].astype(float)
    h -= np.mean(h)
    bg = poly[valid]
    x, y = u[valid]*radius, v[valid]*radius
    r = r[valid]
    if kind == "terrace":
        # A bounded tread changes the local tangent plane inside the pad.
        weight = np.clip((1.35-r)/0.6, 0, 1)
        shape = np.column_stack([weight, weight*x, weight*y])
    elif kind == "mound_pit":
        # Compact central relief and its annulus can have opposing signs.
        weight = np.exp(-2*r*r)
        shape = np.column_stack([weight, np.exp(-((r-1)/0.35)**2)])
    else:
        # Angle points across the trench. Fit the depth independently of tilt.
        a = (x*math.cos(angle) + y*math.sin(angle))/scale
        b = (-x*math.sin(angle) + y*math.cos(angle))/scale
        weight = np.exp(-a*a - (b/2.4)**4)
        shape = weight[:,None]
        # A sharp natural crest can be V-shaped in cross section. Let both
        # models fit its flanks so crest curvature cannot masquerade as a cut.
        bg = np.column_stack([bg, np.abs(b), (b/4.5)**3, a*b*b/4.5**3])
    if kind == "mound_pit":
        # Fit asymmetric displaced earth and a sustained drainage channel as
        # nuisance terms. Both nested hypotheses include them, so evidence
        # for a compact feature must survive these natural explanations.
        tangent = _fit(bg, h)[1:3]
        grade = np.linalg.norm(tangent)
        if grade > 1e-5:
            cross = (-x*tangent[1] + y*tangent[0])/(scale*grade)
            channel = np.exp(-2*cross*cross)
            lobe = np.exp(-r*r)
            bg = np.column_stack([bg, x*lobe/scale, y*lobe/scale, channel])
    both = np.column_stack([bg, shape])
    coef = _fit(both, h)
    null = h - bg @ _fit(bg, h)
    err = h - both @ coef
    extra = coef[bg.shape[1]:]
    sse0, sse1 = null @ null, err @ err
    gain = sse0 - sse1
    # Compare spatial blocks instead of counting each interpolated pixel as independent.
    n_eff = min(h.size, h.size * (step / max(3.0, 0.5*scale))**2)
    df = n_eff - len(coef)
    if df <= 3 or gain <= 0:
        return
    variance = max(sse1 / len(h), 0.12**2)
    stat = gain / len(h) / variance * df / len(extra)
    pval = float(f.sf(stat, len(extra), df))
    improvement = gain / max(sse0, 1e-8)
    # A one-sided scarp, open channel or tilted planar facet can drive a
    # strong global contrast. Check the signal in each quadrant as well.
    sector_gain = []
    for sx, sy in [(1,1),(1,-1),(-1,1),(-1,-1)]:
        sector = (sx*x >= 0) & (sy*y >= 0)
        if not np.any(sector):
            return
        sector_gain.append(np.mean(null[sector]**2 - err[sector]**2))
    if min(sector_gain) < -0.01:
        return
    slope = np.hypot(coef[1], coef[2])/radius
    residual = h - bg @ coef[:bg.shape[1]]
    active = (weight > 0.1) if kind == "horikiri" else (r < 1.45)
    # Evaluate shape fit where the feature can contribute. Outside the
    # footprint the observations constrain the terrain continuation.
    local_gain = 1 - np.mean(err[active]**2)/max(np.mean(null[active]**2), 1.e-8)
    improvement = min(local_gain, 2.0*improvement)
    if kind == "terrace":
        # Check the actual gradient of the tread, independently of its fitted
        # window. A hillslope dipole can otherwise be interpreted as cut/fill.
        inside = r < 0.65
        if np.count_nonzero(inside) < 5:
            return
        tangent = _fit(bg[inside, :3], h[inside])
        measured_tread = np.hypot(*tangent[1:3])/radius
        if measured_tread > min(0.19, 0.55*slope):
            return
        tread_error = h[inside] - bg[inside, :3] @ tangent
        if np.percentile(np.abs(tread_error), 80) > 0.22:
            return
        tread = np.hypot(coef[1]/radius + extra[1], coef[2]/radius + extra[2])
        relief = np.hypot(*extra[1:])*scale
        if slope < 0.23 or tread > min(0.19, 0.48*slope) or relief < 0.65:
            return
        footprint = r <= 0.8
    elif kind == "mound_pit":
        relief = abs(extra[0])
        if relief < 0.45 or abs(extra[1]) > relief or extra[0]*extra[1] > 0.20*relief**2:
            return
        residual = h - bg[:, :6] @ coef[:6]
        center_height = np.median(residual[r <= 0.6])
        rim = (r >= 0.75) & (r <= 1.3)
        sector_id = ((np.arctan2(y, x) + np.pi) * (4/np.pi)).astype(int) % 8
        heights = [np.median(residual[rim & (sector_id == i)]) for i in range(8)
                   if np.any(rim & (sector_id == i))]
        if len(heights) < 6:
            return
        heights = np.asarray(heights)
        contrast = np.sign(extra[0])*(center_height-heights)
        if np.mean(contrast >= 0.25*relief) < 0.75:
            return
        # A sloping closed pit may lack an elevated crest on its uphill side.
        # Require a raised rim relative to the exterior on the majority of
        # observed spokes, or a deep floor enclosed on every observed spoke.
        if extra[0] < 0 and np.mean(heights > 0.04*relief) < 0.6 and np.min(contrast) < 0.45*relief:
            return
        footprint = r <= 0.75
    else:
        relief = -extra[0]
        # A ridge has negative cross-crest curvature, and the trench cuts
        # across that crest. Reject a sustained downhill channel.
        axis = np.array([-math.sin(angle), math.cos(angle)])
        curvature = np.array([[2*coef[3],coef[4]], [coef[4],2*coef[5]]])/radius**2
        ridge_curv = axis @ curvature @ axis
        along_grade = abs(np.dot(axis, coef[1:3]))/radius
        if relief < 0.65 or (ridge_curv > -0.003 and coef[6]/scale > -0.04) or along_grade > max(0.10, 0.78*slope):
            return
        cross = np.array([math.cos(angle), math.sin(angle)])
        crest_curvature = ridge_curv + coef[6]/scale**2
        if crest_curvature >= min(-0.003, cross @ curvature @ cross):
            return
        # A cut has supported banks on both sides at several positions along
        # its length. An asymmetric slump can fit a trough at just one station.
        confirmed = 0
        for station in (-1.3, 0.0, 1.3):
            strip = np.abs(b-station) < 0.65
            floor = strip & (np.abs(a) <= 0.65)
            left = strip & (a < -1.0) & (a > -2.4)
            right = strip & (a > 1.0) & (a < 2.4)
            if floor.any() and left.any() and right.any():
                depth = min(np.median(residual[left]), np.median(residual[right])) - np.median(residual[floor])
                confirmed += depth > 0.35*relief
        if confirmed < 2:
            return
        footprint = weight >= 0.4
    if relief > 1.25*scale or not footprint.any():
        return
    return pval, improvement, relief, slope


def scan_profiles(dtm, rho, dx, min_rho):
    """Generate scale-space extrema, then test their 2-D local relief."""
    stride = max(1, round(1.5/dx))
    step = stride*dx
    measured = (rho >= min_rho) & np.isfinite(dtm)
    sigma = max(0.5, 0.7/dx)
    weights = gaussian_filter(measured.astype(np.float32), sigma, mode="nearest")
    smooth = gaussian_filter(np.where(measured, dtm, 0), sigma, mode="nearest")
    np.divide(smooth, weights, out=smooth, where=weights > 0)
    # Give each block one measured representative. Track its true position so
    # patchy ground coverage cannot introduce a spurious cross-slope step.
    z = dtm[::stride, ::stride].copy()
    valid = np.zeros(z.shape, bool)
    row_offset = np.zeros(z.shape, np.int16)
    col_offset = np.zeros(z.shape, np.int16)
    positions = [(dy, dx_) for dy in range(stride) for dx_ in range(stride)]
    middle = (stride-1)/2
    for dr, dc in sorted(positions, key=lambda rc: (rc[0]-middle)**2 + (rc[1]-middle)**2):
        sub = measured[dr::stride, dc::stride]
        box = np.s_[:sub.shape[0], :sub.shape[1]]
        take = sub & ~valid[box]
        z[box][take] = smooth[dr::stride, dc::stride][take]
        row_offset[box][take] = dr
        col_offset[box][take] = dc
        valid[box] |= take
    offsets = (row_offset*dx, col_offset*dx)
    del smooth, weights, measured
    macro = gaussian_filter(z, 10/step)
    my, mx = np.gradient(macro, step)
    bg_grade = np.hypot(mx, my)
    fine = gaussian_filter(z, 1.4/step)
    gy, gx = np.gradient(fine, step)
    grade = np.hypot(gx, gy)
    # Long connected contour treads can be cut into apparent isolated platforms
    # by single-cell slope noise. Measure connectivity on the smoothed surface.
    ribbon = binary_closing((grade < 0.20) & (bg_grade > 0.22))
    lbl, _ = label(ribbon, structure=np.ones((3,3)))
    roads = np.zeros_like(ribbon)
    for idx, box in enumerate(find_objects(lbl), 1):
        if box is None:
            continue
        length = max(sl.stop-sl.start for sl in box)*step
        if length < 45:
            continue
        component = lbl[box] == idx
        if component.sum()*step**2/length < 7.0:
            roads[box] |= component
    roads = binary_dilation(roads, iterations=max(1,round(4/step)))
    proposals = []
    family_size = 0
    measured_centres = int(np.count_nonzero(valid))
    for scale in (3., 5., 8.):
        sm = gaussian_filter(z, max(0.7, 0.48*scale/step))
        gy, gx = np.gradient(sm, step)
        yy, xy = np.gradient(gy, step)
        _, xx = np.gradient(gx, step)
        center = 0.5*(xx+yy)
        spread = np.hypot(0.5*(xx-yy), xy)
        angle = 0.5*np.arctan2(2*xy, xx-yy)
        # A compensated circular contrast cancels the response of a plane
        # and a quadratic hillside. The broad ring is a control for natural
        # curvature. Keep both isotropic relief and Hessian extrema as seeds.
        middle = gaussian_filter(z, scale/step)
        outer = gaussian_filter(z, 2*scale/step)
        radial = (middle-sm) - (1-0.48**2)/3*(outer-middle)
        channels = [
            ("mound_pit", scale**2*(np.abs(center)-0.65*spread), 0.19),
            ("mound_pit", np.abs(radial), 0.12),
            ("horikiri", scale**2*(center+spread), 0.36),
        ]
        if scale >= 5:
            tread = np.hypot(gx, gy)
            channels.append(("terrace", bg_grade / np.maximum(0.04, tread), 1.55))
        for kind, score, floor in channels:
            family_size += measured_centres
            peaks = (score == maximum_filter(score, size=2*round(scale/step)+1)) & (score > floor)
            for row, col in zip(*np.nonzero(peaks)):
                proposals.append((kind, scale, row, col, float(angle[row,col])))
    hits = []
    supported_count = 0
    for kind, scale, row, col, angle in proposals:
        # A sampled maximum may lie in a single empty cell. Test only adjacent
        # measured centres, and retain the same coverage checks on each model.
        centres = [(row, col)]
        if not valid[row,col]:
            centres = [(r,c) for r,c in [(row-1,col),(row+1,col),(row,col-1),(row,col+1)]
                       if 0 <= r < z.shape[0] and 0 <= c < z.shape[1] and valid[r,c]]
        if not centres:
            continue
        supported_count += 1
        # The extremum of a curvature filter need not have the footprint width
        # of the filter. Correct the local search across widths and centres.
        trials = len(centres)*3
        best = None
        for r,c in centres:
            for width in (0.8*scale, scale, 1.25*scale):
                result = _profile(z, valid, r, c, step, kind, width, angle, offsets)
                if result is None:
                    continue
                pval, improvement, relief, slope = result
                if improvement < 0.58:
                    continue
                if best is None or pval < best[0]:
                    best = (pval, r, c, width, improvement, relief, slope)
        if best:
            pval, r, c, width, improvement, relief, slope = best
            hits.append((kind, int(r*stride+row_offset[r,c]), int(c*stride+col_offset[r,c]),
                         width, angle, min(1.0, pval*trials),
                         improvement, relief, slope, bool(roads[r,c])))
    return len(proposals), supported_count, hits, family_size
