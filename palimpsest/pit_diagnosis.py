"""Replay the opened pilot and audit the actual profile fits near its known pit centres."""
import argparse
import ast
import inspect
import json
import math
import sys
import textwrap
from collections import Counter
from pathlib import Path
from unittest.mock import patch

import laspy
import numpy as np
from scipy.ndimage import map_coordinates

from palimpsest import profiles
from palimpsest.blind_trial import digest, method_hashes, save
from palimpsest.detector import detect_candidates
from palimpsest.export import build_gsi_sampler
from palimpsest.lidar import StudyZoneGrid, stream_study_zone
from palimpsest.provenance import confirm_raw_ground


def load_grid(work, mode):
    path = work / (mode + "_grid.npz")
    inputs = work / mode
    x0, y0, *_ = json.loads((inputs / "study_zone.json").read_text())["bounds_epsg6676"]
    if not path.exists():
        grid = stream_study_zone(inputs)
        np.savez(path, **{k: getattr(grid, k) for k in ("dtm", "chm", "rho_gnd", "dsm")})
        return grid
    with np.load(path) as data:
        return StudyZoneGrid(**dict(data), x0=x0, y0=y0, dx=.5, epsg=6676, peak_rss_gb=0.)


def run_detection(grid, inputs):
    osm = json.loads((inputs / "osm/osm_features.json").read_text())
    anchors = json.loads((inputs / "osm/historic_anchors.json").read_text())
    osm["osm_historic_and_peak_features"] = anchors.get("osm_historic_and_peak_features", [])
    # The production detector computes its required terrain derivatives when omitted.
    result = detect_candidates(grid.dtm, grid.chm, grid.rho_gnd, {}, osm, build_gsi_sampler(inputs),
                               x0=grid.x0, y0=grid.y0, dx=grid.dx)
    confirm_raw_ground(result, grid, inputs)
    return result


def guarded_exits(function, exit_type):
    lines, first = inspect.getsourcelines(function)
    tree = ast.parse(textwrap.dedent("".join(lines)))
    return {first + child.lineno - 1: ast.unparse(node.test)
            for node in ast.walk(tree) if isinstance(node, ast.If)
            for child in node.body if isinstance(child, exit_type)}


def fits_near_sites(grid, sites, inputs):
    original = profiles._profile
    guards = guarded_exits(original, ast.Return)
    discarded = guarded_exits(detect_candidates, ast.Continue)
    observed = {s["id"]: [] for s in sites}
    for site in sites:
        site["discarded_profiles"] = []

    def detector_trace(frame, event, value):
        if frame.f_code is not detect_candidates.__code__:
            return None
        if event == "line" and frame.f_lineno in discarded:
            loc = frame.f_locals
            if loc["kind"] == "mound_pit":
                x = grid.x0 + (loc["col"]+.5)*grid.dx
                y = grid.y0 + (loc["row"]+.5)*grid.dx
                for site in sites:
                    if math.hypot(site["x"]-x, site["y"]-y) <= 14:
                        reason = discarded[frame.f_lineno]
                        record = dict(x=x, y=y, p=loc["pv"], reason=reason)
                        if "gap_m" in reason:
                            coverage = loc["coverage"]
                            core = loc["distance"] <= 0.65 * loc["scale"]
                            record.update(core_support=float(loc["support"][core].mean()),
                                          supported_sectors=int(np.count_nonzero(coverage >= .50)),
                                          weakest_sector=float(np.min(coverage)),
                                          gap_m=float(loc["gap_m"]), scale_m=float(loc["scale"]))
                        site["discarded_profiles"].append(record)
        return detector_trace

    def logged(z, valid, r, c, step, kind, width, angle, offsets):
        args = (z, valid, r, c, step, kind, width, angle, offsets)
        if kind != "mound_pit":
            return original(*args)
        x = grid.x0 + c * step + offsets[1][r, c] + grid.dx / 2
        y = grid.y0 + r * step + offsets[0][r, c] + grid.dx / 2
        nearby = [s for s in sites if math.hypot(x-s["x"], y-s["y"]) <= 14]
        if not nearby:
            return original(*args)
        row = dict(x=float(x), y=float(y), width_m=float(width))

        def trace(frame, event, value):
            if frame.f_code is not original.__code__:
                return None
            if event == "return":
                row["gate"] = guards.get(frame.f_lineno, "profile fitted")
                for name in ("pval", "improvement", "relief"):
                    if name in frame.f_locals:
                        row[name] = float(frame.f_locals[name])
            return trace

        previous = sys.gettrace()
        sys.settrace(trace)
        try:
            value = original(*args)
        finally:
            sys.settrace(previous)
        if value is not None:
            row["gate"] = "accepted profile" if value[1] >= .58 else "minimum profile improvement"
        for s in nearby:
            observed[s["id"]].append(row)
        return value

    previous = sys.gettrace()
    with patch.object(profiles, "_profile", logged):
        sys.settrace(detector_trace)
        try:
            result = run_detection(grid, inputs)
        finally:
            sys.settrace(previous)
    for site in sites:
        trials = observed[site["id"]]
        candidates = [dict(kind=c.morphology, x=c.x_6676, y=c.y_6676, p=c.p_value,
                           q=c.q_value, status=c.status, reason=c.rejection_reason,
                           raw_evidence=c.historical_notes)
                      for c in result.candidates if math.hypot(c.x_6676-site["x"], c.y_6676-site["y"]) <= 14]
        site["fits"] = trials
        site["trial_outcomes"] = dict(Counter(t["gate"] for t in trials))
        site["candidates_within_14m"] = candidates
    return result


def raw_profiles(work, base, challenge, sites):
    """Difference the paired raw point records and the two independently reconstructed DTMs."""
    edges = [0, 3, 5, 7, 9, 12]
    buckets = {s["id"]: [[] for _ in edges[1:]] for s in sites}
    bp = next((work / "baseline/lidar").glob("*.laz"))
    cp = next((work / "challenge/lidar").glob("*.las"))
    with laspy.open(bp) as before, laspy.open(cp) as after:
        for b, a in zip(before.chunk_iterator(250000), after.chunk_iterator(250000), strict=True):
            if not (np.array_equal(a.X, b.X) and np.array_equal(a.Y, b.Y)):
                raise ValueError("Paired raw return order changed")
            x, y, z = map(np.asarray, (b.x, b.y, b.z))
            for s in sites:
                d = np.hypot(x-s["x"], y-s["y"])
                keep = d < edges[-1]
                if not keep.any():
                    continue
                rc = [(y[keep]-base.y0)/base.dx-.5, (x[keep]-base.x0)/base.dx-.5]
                near = abs(z[keep]-map_coordinates(base.dtm, rc, order=1, mode="nearest")) <= .60
                changes = np.asarray(a.z)[keep] - z[keep]
                for i, (lo, hi) in enumerate(zip(edges, edges[1:])):
                    mask = near & (d[keep]>=lo) & (d[keep]<hi)
                    if mask.any():
                        buckets[s["id"]][i].append(changes[mask])
    y, x = np.ogrid[:base.dtm.shape[0], :base.dtm.shape[1]]
    for s in sites:
        d = np.hypot(base.x0+(x+.5)*base.dx-s["x"], base.y0+(y+.5)*base.dx-s["y"])
        rings = []
        for i, (lo, hi) in enumerate(zip(edges, edges[1:])):
            ring = (d>=lo) & (d<hi)
            valid = ring & (base.rho_gnd>=.5) & (challenge.rho_gnd>=.5)
            bins = buckets[s["id"]][i]
            raw = np.concatenate(bins) if bins else np.array([])
            rings.append(dict(radius_m=[lo, hi], near_surface_returns=len(raw),
                              raw_median_dz_m=float(np.median(raw)) if raw.size else None,
                              cells=int(ring.sum()), supported_both=int(valid.sum()),
                              dtm_median_dz_m=float(np.median(challenge.dtm[valid]-base.dtm[valid])) if valid.any() else None))
        s["rings"] = rings


def main(work, pilot, dest):
    seal = json.loads((pilot/"commitment.json").read_text())
    if (method_hashes() != seal["method"] or digest(work/"truth.json") != seal["truth_sha256"]
            or digest(next((work/"challenge/lidar").glob("*.las"))) != seal["challenge_sha256"]
            or digest(next((work/"baseline/lidar").glob("*.laz"))) != seal["source_sha256"]):
        raise ValueError("Pilot seal mismatch")
    truth = json.loads((pilot/"unsealed_truth.json").read_text())
    sites = [dict(id=s["id"], x=s["x"], y=s["y"], band=s["band"], role="injected pit")
             for s in truth["sites"] if s["kind"]=="mound_pit"]
    for a in json.loads((pilot/"results.json").read_text())["alerts"]:
        if a["outcome"]=="novel" and a["kind"]=="mound_pit":
            sites.append(dict(id=a["id"], x=a["x"], y=a["y"], band=a["band"], role="novel background alert"))
    base, challenge = (load_grid(work, mode) for mode in ("baseline", "challenge"))
    raw_profiles(work, base, challenge, sites)
    for mode, grid in (("challenge", challenge), ("baseline", base)):
        result = fits_near_sites(grid, sites, work / mode)
        expected = json.loads((pilot/(mode+"_predictions.json")).read_text())["survivors"]
        actual = [dict(x=c.x_6676, y=c.y_6676, kind=c.morphology, id=c.candidate_id) for c in result.survivors]
        if expected != actual:
            raise ValueError(f"{mode} replay disagrees with sealed predictions")
        for s in sites:
            s[mode] = {k: s.pop(k) for k in ("fits","trial_outcomes","candidates_within_14m","discarded_profiles")}
        save(dest, dict(tile=seal["tile"], method=seal["method"], sites=sites, replayed_through=mode))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("work", type=Path)
    p.add_argument("pilot", type=Path)
    p.add_argument("dest", type=Path)
    a = p.parse_args()
    main(a.work, a.pilot, a.dest)
