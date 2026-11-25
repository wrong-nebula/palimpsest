"""Build the compact public atlas from the frozen basin export and the two research pilots."""
import argparse
import json
import shutil
import struct
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import rasterio
from palimpsest.coverage import write_field_map


def build(root, dest):
    source=root/"data/output"
    data=dest/"bench/data"
    data.mkdir(parents=True,exist_ok=True)
    dist=root/"viewer/dist"
    shutil.copy2(dist/"index.html",dest/"bench")
    shutil.copytree(dist/"assets",dest/"bench/assets",dirs_exist_ok=True)
    def copy(rel):
        target=data/rel
        target.parent.mkdir(exist_ok=True,parents=True)
        shutil.copy2(source/rel,target)
    records=json.loads((source/"candidates.json").read_text())
    support=json.loads((source/"field_support.json").read_text())
    selected=[]
    for label in ("Class A","Class B","Rejected"):
        selected.append(next(c for c in records["candidates"] if c["temporal_class"]==label and c["pack_file"]))
    for c in selected:
        copy(c["pack_file"])
        for t in c["textures"].values():
            if t:copy(t)
    (data/"candidates.json").write_text(json.dumps({**records, "candidates":selected},ensure_ascii=False))
    for f in ("field_support.json","ground_coverage.u8.gz","ground_coverage.tif","paired_trial/comparison.json",
              "paired_trial/verify_production.json","swiss_pilot/scan.json","swiss_pilot/leads.geojson",
              "swiss_pilot/ground_coverage.tif","swiss_pilot/colab.json"):
        copy(f)
    for tile in ("08OC7981","08OC8838"):
        for f in ("trial_map.html","results.json","unsealed_truth.json"):
            copy(f"paired_trial/{tile}/{f}")
    featured = selected[0]
    catalog = [SimpleNamespace(**record) for record in records["candidates"]]
    detection = SimpleNamespace(candidates=catalog, survivors=[c for c in catalog if c.status=="survivor"])
    write_field_map(data, detection, support, featured_id=featured["candidate_id"])
    # Render the actual north-up red relief image stored in the first published pack.
    buf=(source/featured["pack_file"]).read_bytes()
    nx,ny,x0,y0,dx=struct.unpack_from("<IIddf",buf,8)
    col = (featured["x_6676"] - x0) / dx
    row = ny - (featured["y_6676"] - y0) / dx
    if not (0 <= col < nx and 0 <= row < ny):
        raise ValueError("Featured waypoint falls outside its north-up terrain image")
    layers=np.frombuffer(buf,dtype="<f4",offset=64,count=10*nx*ny).reshape(10,ny,nx)
    rgb=(layers[3:6,::-1,:].clip(0,1)*255).round().astype(np.uint8)
    with rasterio.open(dest/"west-ridge.png","w",driver="PNG",width=nx,height=ny,count=3,dtype="uint8") as im:
        im.write(rgb)
    tests=json.loads((source/"paired_trial/comparison.json").read_text())["pooled"]["frozen"]
    swiss=json.loads((source/"swiss_pilot/scan.json").read_text())
    crater=json.loads((root/"experiments/craters/result.json").read_text())["evaluation"]
    html=(Path(__file__).with_name("atlas.html")).read_text()
    replacements={
        "FEATURE_ID":featured["candidate_id"],
        "FEATURE_NAME":{"horikiri":"Possible ridge cut","terrace":"Possible terrace","mound_pit":"Possible mound or pit"}[featured["morphology"]],
        "FEATURE_X":100*col/nx, "FEATURE_Y":100*row/ny,
        "HELD_TARGETS":sum(v["targets"] for v in tests.values()),
        "HELD_HITS":sum(v["detected"] for v in tests.values()),
        "HELD_FP":sum(v["false_positive_alerts"] for v in tests.values()),
        "TRACKS":sum(v["tracks"] for v in tests.values()),
        "TRACK_HITS":sum(v["track_hits"] for v in tests.values()),
        "SWISS_AREA":swiss["core_area_m2"],"SWISS_HITS":swiss["leads"],
        "CRATER_HITS":crater["tp"],"CRATER_N":crater["tp"]+crater["fn"]+crater["unscored_positive"],
        "LOOK_HITS":crater["fp"],"LOOK_N":crater["tn"]+crater["fp"]+crater["unscored_negative"],
        "BLANK_LOW":f'{support["blank_examples"][0]["mean_16m"]:.2f}',
        "BLANK_HIGH":f'{support["blank_examples"][1]["mean_16m"]:.2f}'}
    for k,v in replacements.items():html=html.replace("{{"+k+"}}",str(v))
    (dest/"index.html").write_text(html)
    (dest/".nojekyll").touch()


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("dest",type=Path)
    a=p.parse_args();build(Path(__file__).resolve().parents[1],a.dest)
