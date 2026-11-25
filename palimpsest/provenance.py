"""Independent raw-return elevation checks for real field waypoints."""

from __future__ import annotations

import math
from pathlib import Path

import laspy
import numpy as np
from scipy.ndimage import map_coordinates

from palimpsest.detector import CandidateRecord, DetectionResult
from palimpsest.lidar import CSFParams, StudyZoneGrid, _cloth_ground_indices, _discover_tiles


def _read_patches(candidates, tiles):
    """Read the intersecting LAZ files once per spatial batch, including tile edges."""
    patches = [[] for _ in candidates]
    for tile in tiles:
        xmin, ymin = tile["mins"][:2]
        xmax, ymax = tile["maxs"][:2]
        targets = [(i, c) for i, c in enumerate(candidates)
                   if xmin - 15 <= c.x_6676 <= xmax + 15 and ymin - 15 <= c.y_6676 <= ymax + 15]
        if not targets:
            continue
        with laspy.open(tile["path"]) as source:
            for chunk in source.chunk_iterator(500_000):
                x, y, z = np.asarray(chunk.x), np.asarray(chunk.y), np.asarray(chunk.z)
                cls = np.asarray(chunk.classification)
                for i, c in targets:
                    inside = (np.abs(x - c.x_6676) <= 15) & (np.abs(y - c.y_6676) <= 15)
                    if inside.any():
                        patches[i].append(np.column_stack((x[inside], y[inside], z[inside], cls[inside])))
    return patches


def _independent_density(c: CandidateRecord, points, grid: StudyZoneGrid):
    if not points:
        return 0., "no raw returns"
    patch = np.vstack(points)
    x, y, z, classification = patch.T
    # A disk of equal nominal area avoids privileging a fitted orientation.
    radius = max(4., math.sqrt(c.area_m2 / math.pi))
    area = math.pi * radius**2
    footprint = (x - c.x_6676)**2 + (y - c.y_6676)**2 <= radius**2
    rows = (y - grid.y0) / grid.dx - 0.5
    cols = (x - grid.x0) / grid.dx - 0.5
    surface = map_coordinates(grid.dtm, [rows, cols], order=1, mode="nearest")
    # Allow twice the cloth distance tolerance for sub-cell slope and sampling.
    agrees = footprint & (np.abs(z - surface) <= 2 * CSFParams().class_threshold)
    survey = np.count_nonzero(agrees & (classification == 2)) / area
    if survey >= 0.5 or len(patch) < 8:
        return survey, "survey ground"
    # Sparse or missing survey labels can still be corroborated directly in
    # the original elevation frame, independently of the broad lower envelope.
    indices = _cloth_ground_indices(np.ascontiguousarray(patch[:, :3]), CSFParams())
    native = np.count_nonzero(agrees[indices]) / area
    return (native, "local cloth") if native > survey else (survey, "survey ground")


def confirm_raw_ground(result: DetectionResult, grid: StudyZoneGrid, cache_dir: Path) -> None:
    """Falsify elevated or poorly supported features before issuing a field waypoint."""
    tiles, _, _ = _discover_tiles(cache_dir)
    ranked = sorted(result.survivors, key=lambda c: (int(c.y_6676 // 300), c.x_6676))
    for start in range(0, len(ranked), 24):
        group = ranked[start:start + 24]
        for c, patch in zip(group, _read_patches(group, tiles)):
            density, source = _independent_density(c, patch, grid)
            evidence = f"Elevation-confirming {source} density={density:.3f} pts/m²."
            if density < 0.5:
                c.status = "rejected"
                c.temporal_class = "Rejected"
                c.rejection_reason = "low_rho_gnd"
                c.confidence_score = 0.
            c.historical_notes += " " + evidence

    result.survivors = [c for c in result.survivors if c.status == "survivor"]
    result.candidates = result.survivors + [c for c in result.candidates if c.status == "rejected"]
    for index, c in enumerate(result.candidates, 1):
        c.candidate_id = f"PLMP-{index:04d}"
    result.funnel["after_raw_ground_confirmation"] = len(result.survivors)
    result.funnel["survivors_total"] = len(result.survivors)
