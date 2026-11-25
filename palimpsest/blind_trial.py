"""Prepare a held-out raw-return challenge, predict without labels, then unseal and score."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import secrets
from pathlib import Path

import laspy
import numpy as np
from scipy.ndimage import gaussian_filter, map_coordinates
from scipy.optimize import linear_sum_assignment
from shapely.geometry import LineString, Point

from palimpsest.coverage import CALIBRATION_KEYS, EDGES, context_density, write_density_map
from palimpsest.derivatives import compute_all_derivatives
from palimpsest.detector import detect_candidates
from palimpsest.export import build_gsi_sampler
from palimpsest.lidar import StudyZoneGrid, stream_study_zone
from palimpsest.provenance import confirm_raw_ground

TILE = "08OC8819"
KINDS = ("terrace", "mound_pit", "horikiri", "forestry_track", "forestry_track")
METHOD = ("detector", "profiles", "derivatives", "lidar", "provenance")


def save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)+"\n")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def method_hashes():
    return {m: digest(Path(__file__).with_name(m+".py")) for m in METHOD}


def band(mean):
    return int(np.searchsorted(EDGES, mean, side="right"))


def lay_out(grid, rng):
    z = gaussian_filter(grid.dtm, 8)
    gy, gx = np.gradient(z,grid.dx)
    yy, xy = np.gradient(gy,grid.dx)
    _, xx = np.gradient(gx,grid.dx)
    context = context_density(grid.rho_gnd, grid.dx)
    ny, nx = z.shape
    # Jittered, non-overlapping plots. No detector output participates in placement.
    pool=[]
    for r0 in range(56,ny-55,83):
        for c0 in range(56,nx-55,83):
            r,c=r0+int(rng.integers(-5,6)),c0+int(rng.integers(-5,6))
            if grid.chm[r-24:r+24,c-24:c+24].mean()<5 or grid.rho_gnd[r,c]<.5:continue
            mean=float(context[r,c])
            if band(mean)==0:continue
            slope=float(np.hypot(gx[r,c],gy[r,c]))
            eig,vec=np.linalg.eigh([[xx[r,c],xy[r,c]],[xy[r,c],yy[r,c]]])
            pool.append(dict(row=r,col=c,band=band(mean),rho=mean,slope=slope,crest=float(eig[0]),
                             aspect=float(np.arctan2(gy[r,c],gx[r,c])),
                             ridge=float(np.arctan2(vec[1,1],vec[0,1]))))
    rng.shuffle(pool)
    chosen=[]
    # Place slope-dependent features first. Lack of eligible sites stays visible.
    for kind in ("horikiri","terrace","forestry_track","mound_pit","forestry_track"):
        for b in range(1,5):
            options=[p for p in pool if p["band"]==b
                     and (kind!="horikiri" or p["crest"]<-.005)
                     and (kind not in ("terrace","forestry_track") or p["slope"]>=.20)]
            if not options:continue
            p=options[0];pool.remove(p)
            p.update(kind=kind,id=f"plot-{len(chosen)+1:02d}",x=grid.x0+(p["col"]+.5)*grid.dx,
                     y=grid.y0+(p["row"]+.5)*grid.dx)
            chosen.append(p)
    return chosen


def prepare(cache, work, out, seed=None, tile=TILE):
    if tile not in {p.stem for p in (cache/"lidar").glob("*.laz")}:
        raise ValueError(f"Unknown cached tile {tile!r}")
    if (out/"commitment.json").exists():
        raise RuntimeError("A trial is already sealed in this directory")
    for name in ("baseline","challenge"):
        d=work/name
        (d/"lidar").mkdir(exist_ok=True,parents=True)
        for layer in ("osm","gsi"):
            (d/layer).symlink_to((cache/layer).resolve(),target_is_directory=True)
    src=(cache/"lidar"/(tile+".laz")).resolve()
    (work/"baseline"/"lidar"/src.name).symlink_to(src)
    with laspy.open(src) as f:
        x0,y0=np.round(f.header.mins[:2]/100)*100
    bounds=[x0,y0,x0+400,y0+300]
    for mode in ("baseline","challenge"):
        save(work/mode/"study_zone.json",dict(epsg=6676,bounds_epsg6676=bounds))
    grid=stream_study_zone(work/"baseline")
    np.savez(work/"baseline_grid.npz",dtm=grid.dtm,dsm=grid.dsm,chm=grid.chm,rho_gnd=grid.rho_gnd)
    seed=secrets.randbits(63) if seed is None else seed
    rng=np.random.default_rng(seed)
    sites=lay_out(grid,rng)
    delta=np.zeros_like(grid.dtm)
    for p in sites:
        r,c=p["row"],p["col"]
        off=48; y,x=np.mgrid[-off:off+1,-off:off+1]*grid.dx
        dist=np.hypot(x,y); sl=np.s_[r-off:r+off+1,c-off:c+off+1]
        terrain=grid.dtm[sl]
        size=float(rng.uniform(5.5,8.5))
        theta=p["aspect"] if p["kind"]!="horikiri" else p["ridge"]
        a=x*math.cos(theta)+y*math.sin(theta); b=-x*math.sin(theta)+y*math.cos(theta)
        if p["kind"]=="terrace":
            edge=np.clip((size+2-dist)/2,0,1)
            dz=(float(grid.dtm[r,c])-terrain)*edge
        elif p["kind"]=="mound_pit":
            dz=-rng.uniform(1.1,1.7)*np.exp(-(dist/(size*.50))**4)+.6*np.exp(-((dist-size)/1.5)**2)
        elif p["kind"]=="horikiri":
            dz=-rng.uniform(1.7,2.8)*np.exp(-(a/rng.uniform(2.8,4.2))**2-(b/rng.uniform(8,12))**4)
        else:
            length=float(rng.uniform(32,40)); width=float(rng.uniform(3,4.5))
            def curve(v):return 2.5*np.sin(v/7.0)
            transverse=a-curve(b)
            edge=np.clip((width/2+1-abs(transverse)),0,1)*np.clip((length/2+1-abs(b)),0,1)
            # Grade a curved contour bench to the centreline elevation.
            xc=curve(b)*math.cos(theta)-b*math.sin(theta);yc=curve(b)*math.sin(theta)+b*math.cos(theta)
            centreline=map_coordinates(grid.dtm,[r+yc/grid.dx,c+xc/grid.dx],order=1)
            dz=(centreline-terrain)*edge
            v=np.linspace(-length/2,length/2,17)
            p["line"]=np.column_stack((p["x"]+curve(v)*math.cos(theta)-v*math.sin(theta),
                                      p["y"]+curve(v)*math.sin(theta)+v*math.cos(theta))).tolist()
            p["width_m"]=width
        delta[sl]+=gaussian_filter(dz,rng.uniform(.7,1.8)).astype(np.float32)
    dst=work/"challenge"/"lidar"/(tile+".las")
    with laspy.open(src) as inp, laspy.open(dst,mode="w",header=inp.header) as writer:
        for chunk in inp.chunk_iterator(300000):
            x,y,z=np.asarray(chunk.x),np.asarray(chunk.y),np.asarray(chunk.z)
            rc=[(y-y0)/grid.dx-.5,(x-x0)/grid.dx-.5]
            old=map_coordinates(grid.dtm,rc,order=1,mode="nearest")
            dz=map_coordinates(delta,rc,order=1,mode="nearest")
            # Keep canopy returns in place. Move near-surface measurements with the earthwork.
            chunk.z=z+np.where(np.abs(z-old)<=.60,dz,0.)
            writer.write_points(chunk)
    save(work/"truth.json",dict(tile=tile,seed=seed,sites=sites))
    save(out/"commitment.json",dict(tile=tile,source_sha256=digest(src),truth_sha256=digest(work/"truth.json"),
                                    challenge_sha256=digest(dst),method=method_hashes(),desired_per_band=list(KINDS),
                                    match_radius_m=14,track_centreline_buffer_m=4,
                                    protocol="One-to-one target match, then track footprint plus 4 m, then baseline within 14 m. All other alerts are novel. No reroll."))
    print("Challenge sealed.",flush=True)


def predict(inputs, out, name, baseline_npz=None):
    commitment=json.loads((out/"commitment.json").read_text())
    if commitment["method"]!=method_hashes():raise RuntimeError("Frozen method changed")
    if name=="challenge" and digest(next((inputs/"lidar").glob("*.las")))!=commitment["challenge_sha256"]:
        raise RuntimeError("Challenge bytes changed")
    if baseline_npz is None:
        grid=stream_study_zone(inputs)
    else:
        x0,y0,*_=json.loads((inputs/"study_zone.json").read_text())["bounds_epsg6676"]
        with np.load(baseline_npz) as z:
            grid=StudyZoneGrid(**dict(z),x0=x0,y0=y0,dx=.5,epsg=6676,peak_rss_gb=0.)
    derivs=compute_all_derivatives(grid.dtm,grid.dx)
    osm=json.loads((inputs/"osm/osm_features.json").read_text())
    anchors=json.loads((inputs/"osm/historic_anchors.json").read_text())
    osm["osm_historic_and_peak_features"]=anchors.get("osm_historic_and_peak_features",[])
    result=detect_candidates(grid.dtm,grid.chm,grid.rho_gnd,derivs,osm,build_gsi_sampler(inputs),x0=grid.x0,y0=grid.y0,dx=grid.dx)
    confirm_raw_ground(result,grid,inputs)
    save(out/(name+"_predictions.json"),dict(method=method_hashes(),funnel=result.funnel,
         survivors=[dict(x=c.x_6676,y=c.y_6676,kind=c.morphology,id=c.candidate_id) for c in result.survivors]))
    if name=="baseline":
        write_density_map(out,grid)
    print("Saved predictions for",name,flush=True)


def score(work,out):
    commit=json.loads((out/"commitment.json").read_text())
    preds=[json.loads((out/(m+"_predictions.json")).read_text()) for m in ("baseline","challenge")]
    if any(p["method"]!=commit["method"] for p in preds) or digest(work/"truth.json")!=commit["truth_sha256"]:
        raise RuntimeError("Seal mismatch")
    save(out/"prediction_commitment.json",{m:digest(out/(m+"_predictions.json")) for m in ("baseline","challenge")})
    layout=(work/"truth.json").read_bytes()
    (out/"sealed_layout.json").write_bytes(layout)
    truth=json.loads(layout);sites=truth["sites"]
    alerts=preds[1]["survivors"];base=preds[0]["survivors"]
    bins=[dict(band=b,targets=0,detected=0,tracks=0,track_hits=0,track_alerts=0,duplicates=0,novel=0,baseline_unconfirmed=0) for b in ("< 0.5",*CALIBRATION_KEYS)]
    features=[s for s in sites if s["kind"]!="forestry_track"]
    tracks=[s for s in sites if s["kind"]=="forestry_track"]
    for s in sites:
        s["hit"]=False
        bins[s["band"]]["tracks" if s in tracks else "targets"]+=1
    def dist(a,b):return math.hypot(a["x"]-b["x"],a["y"]-b["y"])
    if alerts and features:
        cost=np.array([[dist(a,s) for s in features] for a in alerts])
        ids,js=linear_sum_assignment(np.where(cost<=14,cost,1e6))
        for i,j in zip(ids,js):
            if cost[i,j]<=14:
                s=features[j];s["hit"]=True;alerts[i].update(outcome="target",site=s["id"],band=s["band"])
                bins[s["band"]]["detected"]+=1
    import rasterio
    with rasterio.open(out/"ground_density.tif") as ds:
        for a in alerts:
            if "outcome" in a:continue
            dup=next((s for s in features if dist(a,s)<=14),None)
            near=[(LineString(s["line"]).distance(Point(a["x"],a["y"])),s) for s in tracks]
            matched=[(d,s) for d,s in near if d<=s["width_m"]/2+4]
            if dup:
                a.update(outcome="duplicates",site=dup["id"],band=dup["band"])
            elif matched:
                _,s=min(matched,key=lambda t:t[0])
                if not s["hit"]:bins[s["band"]]["track_hits"]+=1
                s["hit"]=True;a.update(outcome="track_alerts",site=s["id"],band=s["band"])
            else:
                mean=float(next(ds.sample([(a["x"],a["y"])],indexes=2))[0])
                outcome="baseline_unconfirmed" if any(dist(a,b)<=14 for b in base) else "novel"
                a.update(outcome=outcome,band=band(mean))
            bins[a["band"]][a["outcome"]]+=1
    for row in bins:
        row["recall"]=row["detected"]/row["targets"] if row["targets"] else None
        row["false_positive_alerts"]=row["track_alerts"]+row["novel"]+row["duplicates"]
    save(out/"unsealed_truth.json",truth)
    save(out/"results.json",dict(tile=commit["tile"],bands=bins,alerts=alerts,source="Synthetic earthworks and unmapped forestry-track decoys in real held-out airborne returns."))
    write_trial_map(out, sites, alerts, commit["tile"])
    print("Blinded challenge scored.",flush=True)


def write_trial_map(out, sites, alerts, tile=TILE):
    """North-up field sheet with challenge labels revealed only after scoring."""
    import base64
    from html import escape

    import rasterio
    from rasterio.io import MemoryFile
    from palimpsest.coverage import COLORS, LABELS

    with rasterio.open(out/"ground_coverage.tif") as ds:
        codes=ds.read(1)
        x0,_,_,y1=ds.bounds
        dx=ds.res[0]
    h,w=codes.shape
    palette=np.array([list(bytes.fromhex(c[1:])) for c in COLORS],np.uint8)
    with MemoryFile() as mem:
        with mem.open(driver="PNG",width=w,height=h,count=3,dtype="uint8") as im:
            im.write(palette[codes].transpose(2,0,1))
        image=base64.b64encode(mem.read()).decode()
    def pos(x,y):
        return (x-x0)/dx,(y1-y)/dx
    shapes=[]
    for s in sites:
        x,y=pos(s["x"],s["y"])
        descr=escape(f"{s['id']} · {s['kind']} · {'detected' if s['hit'] else 'no hit'} · {s['rho']:.2f} pts/m²")
        if s["kind"]=="forestry_track":
            points=" ".join(f"{a:.1f},{b:.1f}" for a,b in (pos(*pt) for pt in s["line"]))
            shapes.append(f'<polyline points="{points}" fill="none" stroke="#17142b" stroke-width="5"/><polyline points="{points}" fill="none" stroke="white" stroke-width="2" stroke-dasharray="4 3"><title>{descr}</title></polyline>')
        elif s["hit"]:
            shapes.append(f'<circle cx="{x}" cy="{y}" r="7" fill="#fff" stroke="#141b29" stroke-width="3"><title>{descr}</title></circle>')
        else:
            shapes.append(f'<g transform="translate({x} {y})"><title>{descr}</title><circle r="8" fill="#fff"/><path d="M-4 -4l8 8m0 -8l-8 8" stroke="#27162a" stroke-width="2.5"/></g>')
    for a in alerts:
        if a["outcome"]!="target":
            x,y=pos(a["x"],a["y"])
            shapes.append(f'<path transform="translate({x:.1f} {y:.1f})" d="M0 -6l6 6 -6 6 -6 -6z" fill="#8b59ff" stroke="#fff" stroke-width="2"><title>{escape(a["outcome"])}</title></path>')
    bins=json.loads((out/"results.json").read_text())["bands"]
    rows="".join(f"<tr><td>{escape(b['band'])}</td><td>{b['detected']}/{b['targets']}</td><td>{b['track_hits']}/{b['tracks']}</td><td>{b['false_positive_alerts']}</td><td>{b['baseline_unconfirmed']}</td></tr>" for b in bins)
    legend=" ".join(f'<span><i style="background:{color}"></i>{escape(label)}</span>' for color,label in zip(COLORS,LABELS))
    html=f'''<!doctype html><meta charset="utf-8"><link rel="icon" href="data:,"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Held-out tile {tile}</title><style>
body{{max-width:980px;margin:1.5rem auto;padding:0 1rem;font:16px/1.5 system-ui;color:#19323a;background:#faf9f5}}svg{{width:100%}}span{{display:inline-block;margin:0 .6rem .3rem 0}}i{{display:inline-block;width:.85rem;height:.85rem;margin-right:.35rem}}table{{border-collapse:collapse}}td,th{{text-align:left;padding:.4rem .8rem;border-bottom:1px solid #ccc}}a{{color:#145966}}</style><h1>Blinded field trial · {tile}</h1><p>Colors show pre-injection ground support. Symbols show the challenge predictions after raw returns were modified and reclassified. North up, EPSG:6676. White circles mark recovered features and crossed circles mark misses. Dashed tracks are decoys. Purple diamonds mark other alerts, including baseline detections.</p>
<svg viewBox="0 0 {w} {h}" aria-label="Unsealed tile, ground coverage, known features, decoys and predictions"><image width="{w}" height="{h}" href="data:image/png;base64,{image}"/>{''.join(shapes)}<rect x="10" y="{h-32}" width="120" height="24" fill="white"/><path d="M20 {h-14}h100" stroke="black" stroke-width="3"/><text x="20" y="{h-19}" font-size="11">50 m</text></svg>
<p>{legend} pts/m²</p><table><tr><th>Ground pts/m²</th><th>Target recall</th><th>Track hits</th><th>FP alerts</th><th>Baseline alerts</th></tr>{rows}</table><p>0/0 denotes an untested band. FP alerts count track alerts, duplicate target alerts and novel background alerts. Pre-existing baseline alerts have unknown field truth. <a href="results.json">Scored predictions</a> · <a href="unsealed_truth.json">Revealed layout</a></p>'''
    (out/"trial_map.html").write_text(html)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage",choices=["prepare","baseline","challenge","score"])
    parser.add_argument("--work",type=Path,required=True);parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--cache",type=Path,default=Path("data/cache"))
    parser.add_argument("--seed",type=int,help="Reproduce a published layout in new, empty work and output directories")
    parser.add_argument("--tile", default=TILE, help="Cached tile ID for preparation")
    a=parser.parse_args();a.out.mkdir(parents=True,exist_ok=True)
    if a.stage=="prepare":prepare(a.cache,a.work,a.out,a.seed,a.tile)
    elif a.stage=="score":score(a.work,a.out)
    else:predict(a.work/a.stage,a.out,a.stage,a.work/"baseline_grid.npz" if a.stage=="baseline" else None)
