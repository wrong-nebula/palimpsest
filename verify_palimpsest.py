#!/usr/bin/env python3
"""PALIMPSEST Independent Verification & Adversarial Oracle Runner.

CLI:
    .venv/bin/python verify_palimpsest.py [--self-test | --tier 1|2|3|all] [--verify-sha] [--json-out path]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import resource
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psutil


ROOT_DIR = Path(__file__).resolve().parent
ORACLE_MANIFEST = ROOT_DIR / "ORACLE.sha256"


def get_oracle_files() -> list[Path]:
    """Return deterministic sorted list of all files protected by ORACLE.sha256."""
    files = [ROOT_DIR / "verify_palimpsest.py"]
    oracles_dir = ROOT_DIR / "tests" / "oracles"
    if oracles_dir.exists():
        for p in sorted(oracles_dir.rglob("*")):
            if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc":
                files.append(p)
    return files


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def verify_oracle_sha(manifest_path: Path = ORACLE_MANIFEST) -> dict[str, Any]:
    """Verify ORACLE.sha256 against verify_palimpsest.py and tests/oracles/."""
    if not manifest_path.exists():
        return {"pass": False, "error": f"Missing {manifest_path}", "checked": 0}

    expected: dict[str, str] = {}
    with open(manifest_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split(None, 1)
            if len(parts) != 2:
                return {"pass": False, "error": f"Malformed manifest line: {line!r}", "checked": 0}
            digest, rel = parts[0].strip(), parts[1].strip()
            expected[rel] = digest

    actual_files = {p.relative_to(ROOT_DIR).as_posix(): p for p in get_oracle_files()}
    missing = sorted(set(expected.keys()) - set(actual_files.keys()))
    extra = sorted(set(actual_files.keys()) - set(expected.keys()))
    mismatches = []

    for rel, exp_hex in sorted(expected.items()):
        p = actual_files.get(rel)
        if p is not None:
            got_hex = sha256_file(p)
            if got_hex != exp_hex:
                mismatches.append({"file": rel, "expected": exp_hex, "actual": got_hex})

    passed = (len(expected) > 0 and not missing and not extra and not mismatches)
    return {
        "pass": passed,
        "checked": len(expected),
        "missing": missing,
        "unexpected": extra,
        "mismatches": mismatches,
    }


def _peak_rss_gb() -> float:
    # On macOS ru_maxrss is in bytes; on Linux it's KiB.
    ru = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform == "darwin":
        ru_gb = ru / (1024.0 ** 3)
    else:
        ru_gb = (ru * 1024.0) / (1024.0 ** 3)
    cur_gb = psutil.Process(os.getpid()).memory_info().rss / (1024.0 ** 3)
    return max(ru_gb, cur_gb)


def main() -> int:
    parser = argparse.ArgumentParser(description="PALIMPSEST Independent Oracle Verification Suite")
    parser.add_argument("--self-test", action="store_true", help="Run independent oracle self-tests (no palimpsest/ needed)")
    parser.add_argument("--tier", choices=["1", "2", "3", "all"], default=None, help="Run verification tier(s) against palimpsest/")
    parser.add_argument("--verify-sha", action="store_true", help="Verify ORACLE.sha256 integrity")
    parser.add_argument("--cache", type=Path, default=ROOT_DIR / "data" / "cache", help="Path to data/cache")
    parser.add_argument("--out", type=Path, default=ROOT_DIR / "data" / "output", help="Path to data/output")
    parser.add_argument("--json-out", type=Path, default=None, help="Write structured JSON report to this path")
    args = parser.parse_args()

    if not args.self_test and args.tier is None and not args.verify_sha:
        parser.print_help()
        return 2

    if str(ROOT_DIR) not in sys.path:
        sys.path.insert(0, str(ROOT_DIR))

    report: dict[str, Any] = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "status": "PASS",
        "results": {},
    }
    overall_ok = True

    if args.verify_sha:
        sha_res = verify_oracle_sha()
        report["results"]["oracle_sha256"] = sha_res
        if not sha_res["pass"]:
            overall_ok = False

    if args.self_test:
        from tests.oracles import tier1_analytical, tier1_firewall, tier2_soil_creep, tier3_basin_audit

        st_res = {}
        for name, fn in [
            ("tier1_analytical", tier1_analytical.run_self_test),
            ("tier1_firewall", tier1_firewall.run_self_test),
            ("tier2_soil_creep", lambda: tier2_soil_creep.run_self_test(cache_dir=args.cache)),
            ("tier3_basin_audit", lambda: tier3_basin_audit.run_self_test(cache_dir=args.cache)),
        ]:
            try:
                res = fn()
                st_res[name] = res
                if res.get("status") != "PASS":
                    overall_ok = False
            except Exception as exc:
                st_res[name] = {"status": "FAIL", "error": repr(exc)}
                overall_ok = False
        report["results"]["self_test"] = st_res

    if args.tier is not None:
        tiers = ["1", "2", "3"] if args.tier == "all" else [args.tier]
        if "1" in tiers:
            from tests.oracles.tier1_analytical import run_tier1_analytical
            from tests.oracles.tier1_firewall import run_tier1_firewall

            t1a = run_tier1_analytical()
            t1f = run_tier1_firewall()
            report["results"]["tier1_analytical"] = t1a
            report["results"]["tier1_firewall"] = t1f
            if t1a.get("status") != "PASS" or t1f.get("status") != "PASS":
                overall_ok = False

        if "2" in tiers:
            from tests.oracles.tier2_soil_creep import run_tier2_soil_creep

            t2 = run_tier2_soil_creep(cache_dir=args.cache)
            report["results"]["tier2_soil_creep"] = t2
            if t2.get("status") != "PASS":
                overall_ok = False

        if "3" in tiers:
            from tests.oracles.tier3_basin_audit import run_tier3_basin_audit

            t3 = run_tier3_basin_audit(cache_dir=args.cache, out_dir=args.out)
            report["results"]["tier3_basin_audit"] = t3
            if t3.get("status") != "PASS":
                overall_ok = False

    peak_rss = _peak_rss_gb()
    report["peak_rss_gb"] = peak_rss
    if peak_rss >= 4.0:
        overall_ok = False
    report["status"] = "PASS" if overall_ok else "FAIL"

    text = json.dumps(report, indent=2)
    print(text)
    if args.json_out is not None:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(text + "\n", encoding="utf-8")

    return 0 if overall_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
