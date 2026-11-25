"""PALIMPSEST: Airborne LiDAR Archaeological Prospection & Falsification Pipeline."""

from palimpsest.lidar import (
    CSFParams,
    StudyZoneGrid,
    extract_cutout_points,
    run_csf_tile,
    stream_study_zone,
)
from palimpsest.derivatives import (
    DerivativeBundle,
    benjamini_hochberg_fdr,
    compute_all_derivatives,
    compute_dinf_flow,
    compute_drainage_violation,
    compute_lrm,
    compute_openness,
    compute_rrim,
    compute_svf,
    compute_vat,
)
from palimpsest.detector import (
    CandidateRecord,
    DetectionResult,
    detect_candidates,
)

__all__ = [
    "CSFParams",
    "StudyZoneGrid",
    "run_csf_tile",
    "stream_study_zone",
    "extract_cutout_points",
    "DerivativeBundle",
    "compute_openness",
    "compute_svf",
    "compute_rrim",
    "compute_lrm",
    "compute_vat",
    "compute_dinf_flow",
    "compute_drainage_violation",
    "benjamini_hochberg_fdr",
    "compute_all_derivatives",
    "CandidateRecord",
    "DetectionResult",
    "detect_candidates",
]
