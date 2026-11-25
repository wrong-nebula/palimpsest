"""Compare the frozen detector and a single isolated profile revision before revealing either tile."""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import rasterio

from palimpsest import blind_trial
from palimpsest.blind_trial import digest, save
from palimpsest.coverage import CALIBRATION_KEYS
from palimpsest.pit_diagnosis import load_grid

TILES = ("08OC7981", "08OC8838")
MODES = ("baseline", "challenge")
VARIANT = "compact_floor"
PROMOTION = ("Increase correct-class pit recoveries, preserve each other class's correct recoveries, "
             "and do not increase track hits or novel alerts per support-eligible square kilometre "
             "across these two prespecified tiles.")


def work_dir(root, tile):
    return root / ("palim_paired_" + tile)


def variants(out):
    return [out, out / VARIANT]


def read(path):
    return json.loads(path.read_text())


def prepare_predictions(out, cache, scratch):
    if (out/"paired_prediction_commitment.json").exists():
        raise ValueError("Both arms are already committed. Use the score stage.")
    source = Path(blind_trial.__file__).parent.resolve()
    patch = source / "experiments/compact_floor.patch"
    with tempfile.TemporaryDirectory(prefix="pit-profile-", dir=scratch) as tmp:
        pkg = Path(tmp) / "palimpsest"
        shutil.copytree(source, pkg, ignore=shutil.ignore_patterns("__pycache__"))
        subprocess.run(["patch", "-s", "-p1", "-i", str(patch)], cwd=pkg, check=True)
        hashes = blind_trial.method_hashes()
        alternate = {**hashes, "profiles":digest(pkg/"profiles.py")}
        predictions = {}
        for tile in TILES:
            tile_out = out / tile
            tile_out.mkdir(parents=True, exist_ok=True)
            work = work_dir(scratch, tile)
            if not (tile_out/"commitment.json").exists():
                blind_trial.prepare(cache, work, tile_out, tile=tile)
            seal = read(tile_out/"commitment.json")
            if (seal["tile"] != tile or seal["method"] != hashes
                    or digest(next((work/"baseline/lidar").glob("*.laz"))) != seal["source_sha256"]
                    or digest(next((work/"challenge/lidar").glob("*.las"))) != seal["challenge_sha256"]):
                raise ValueError("Input or method seal mismatch")
            experiment = tile_out / VARIANT
            experiment.mkdir(exist_ok=True)
            save(experiment/"commitment.json", {**seal, "method":alternate, "patch_sha256":digest(patch),
                                               "promotion_rule":PROMOTION})
            for mode in MODES:
                load_grid(work, mode)
                grid = work/(mode+"_grid.npz")
                pred_file = mode+"_predictions.json"
                if not (tile_out/pred_file).exists():
                    blind_trial.predict(work/mode, tile_out, mode, grid)
                # Run in a separate interpreter so both arms import their own frozen package.
                env = {**os.environ, "PYTHONPATH":tmp}
                subprocess.run([sys.executable, "-c",
                                "from pathlib import Path; import sys; from palimpsest.blind_trial import predict; "
                                "inputs, out, mode, grid = sys.argv[1:]; predict(Path(inputs), Path(out), mode, Path(grid))",
                                str((work/mode).resolve()), str(experiment.resolve()), mode, str(grid.resolve())],
                               cwd=tmp, env=env, check=True)
                for arm in variants(tile_out):
                    path = arm/pred_file
                    predictions[str(path.relative_to(out))] = digest(path)
            if digest(tile_out/"ground_coverage.tif") != digest(experiment/"ground_coverage.tif"):
                raise ValueError("Arms used different support maps")
        save(out/"paired_prediction_commitment.json", dict(tiles=TILES, predictions=predictions,
             baseline=hashes, revision=alternate, promotion_rule=PROMOTION, patch_sha256=digest(patch)))


def summarize(arm):
    results = read(arm/"results.json")
    truth = read(arm/"unsealed_truth.json")["sites"]
    sites = {s["id"]:s for s in truth if s["kind"] != "forestry_track"}
    with rasterio.open(arm/"ground_coverage.tif") as raster:
        codes = raster.read(1)
        pixel_area = abs(raster.transform.a*raster.transform.e) / 1e6
        support = np.bincount(codes.ravel(), minlength=6)[1:] * pixel_area
        novel_supported = [0]*5
        for alert in results["alerts"]:
            if alert["outcome"] == "novel":
                code = int(codes[raster.index(alert["x"], alert["y"])])
                if code:
                    novel_supported[code-1] += 1
    scored = {}
    for i, row in enumerate(results["bands"]):
        matches = [a for a in results["alerts"] if a["outcome"] == "target" and a["band"] == i]
        codes_ok = {a["site"] for a in matches if a["kind"] == sites[a["site"]]["kind"]}
        counts = {kind:dict(correct=sum(s["id"] in codes_ok for s in sites.values() if s["kind"] == kind),
                            total=sum(s["band"]==i and s["kind"]==kind for s in sites.values()))
                  for kind in ("terrace", "mound_pit", "horikiri")}
        scored[row["band"]] = {**row, "correct_class":len(codes_ok), "class_counts":counts,
                               "support_km2":float(support[i]), "novel_on_support":novel_supported[i]}
    return scored


def score(out, scratch):
    locked = read(out/"paired_prediction_commitment.json")
    for path, sha in locked["predictions"].items():
        if digest(out/path) != sha:
            raise ValueError("Paired predictions changed after commitment")
    per_tile = {}
    pooled = {}
    for tile in TILES:
        per_tile[tile] = {}
        for name, arm in zip(("frozen", VARIANT), variants(out/tile)):
            blind_trial.score(work_dir(scratch,tile), arm)
            rows = summarize(arm)
            per_tile[tile][name] = rows
            group = pooled.setdefault(name,{})
            for band, r in rows.items():
                g = group.setdefault(band,{})
                for k in ("targets","detected","correct_class","tracks","track_hits","track_alerts","duplicates",
                          "novel","baseline_unconfirmed","false_positive_alerts","support_km2","novel_on_support"):
                    g[k] = g.get(k,0) + r[k]
                kinds = g.setdefault("class_counts",{})
                for kind, counts in r["class_counts"].items():
                    totals = kinds.setdefault(kind,dict(correct=0,total=0))
                    for k in totals:
                        totals[k] += counts[k]
    for bands in pooled.values():
        for g in bands.values():
            g["novel_per_support_km2"] = g["novel_on_support"]/g["support_km2"] if g["support_km2"] else None
    totals = {}
    for arm, bands in pooled.items():
        area = sum(r["support_km2"] for r in bands.values())
        totals[arm] = dict(correct_by_class={kind:sum(r["class_counts"][kind]["correct"] for r in bands.values())
                           for kind in ("mound_pit", "horikiri", "terrace")},
                           track_hits=sum(r["track_hits"] for r in bands.values()),
                           support_km2=area, novel_per_support_km2=sum(r["novel_on_support"] for r in bands.values())/area)
    frozen, revised = totals["frozen"], totals[VARIANT]
    checks = dict(more_correct_pits=revised["correct_by_class"]["mound_pit"] > frozen["correct_by_class"]["mound_pit"],
                  other_classes_preserved=all(revised["correct_by_class"][k] >= frozen["correct_by_class"][k]
                                              for k in ("horikiri","terrace")),
                  no_more_track_hits=revised["track_hits"] <= frozen["track_hits"],
                  no_more_novel_per_km2=revised["novel_per_support_km2"] <= frozen["novel_per_support_km2"])
    save(out/"comparison.json", dict(per_tile=per_tile, pooled=pooled, totals=totals, promotion_rule=PROMOTION,
         promotion_checks=checks, meets_promotion_rule=all(checks.values()),
         density_bands=["< 0.5",*CALIBRATION_KEYS], unit="Pre-injection 16 m context, pts/m²",
         support_km2="Area with native density at least 0.5 pts/m², including tile margins and open terrain. "
         "Rates use novel-alert centres on this support. Baseline alerts have unknown truth."))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("stage", choices=("predict","score"))
    p.add_argument("--cache", type=Path, default=Path("data/cache"))
    p.add_argument("--out", type=Path, default=Path("data/output/paired_trial"))
    p.add_argument("--scratch", type=Path, default=Path(tempfile.gettempdir()))
    a = p.parse_args()
    if a.stage == "predict":
        prepare_predictions(a.out, a.cache, a.scratch)
    else:
        score(a.out, a.scratch)
