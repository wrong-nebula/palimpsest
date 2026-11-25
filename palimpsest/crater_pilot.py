"""Fixed-centre crater morphology pilot using native Copernicus GLO-30 samples."""
import argparse
import csv
import json
import math
from pathlib import Path

import numpy as np
import rasterio
from pyproj import Geod
from rasterio.windows import Window
from scipy.optimize import minimize
from scipy.special import expit

FEATURES = ["rim_over_floor_per_radius", "rim_over_exterior_per_radius", "fraction_enclosed_spokes"]


def sample_site(site):
    lat, lon, diameter = (float(site[k]) for k in ("lat","lon","diam_km"))
    iy, ix = math.floor(lat), math.floor(lon)
    tile = f"Copernicus_DSM_COG_10_{'N' if iy>=0 else 'S'}{abs(iy):02}_00_{'E' if ix>=0 else 'W'}{abs(ix):03}_00_DEM"
    url = f"https://copernicus-dem-30m.s3.amazonaws.com/{tile}/{tile}.tif"
    radius = 500*diameter
    geod = Geod(ellps="WGS84")
    with rasterio.open(url) as src:
        rc = src.index(lon,lat)
        dx = geod.inv(lon,lat,lon+src.res[0],lat)[2]
        dy = geod.inv(lon,lat,lon,lat+src.res[1])[2]
        if radius < 2*max(dx,dy):
            return dict(source=url, reason="fewer than two native pixels per radius")
        n = math.ceil(1.8*radius/min(dx,dy))+2
        win = Window(rc[1]-n,rc[0]-n,2*n+1,2*n+1)
        if win.col_off<0 or win.row_off<0 or win.col_off+win.width>src.width or win.row_off+win.height>src.height:
            return dict(source=url, reason="window crosses tile boundary")
        z = src.read(1,window=win,masked=True).astype(float).filled(np.nan)
        t = src.window_transform(win)
    rr,cc=np.indices(z.shape)
    lng = t.c+(cc+.5)*t.a
    phi = t.f+(rr+.5)*t.e
    angle,_,d = geod.inv(np.full(z.shape,lon),np.full(z.shape,lat),lng,phi)
    r = d/radius
    outer=(r>=1.35)&(r<=1.75)&np.isfinite(z)
    core=(r<.55)&np.isfinite(z)
    rim=(r>=.72)&(r<=1.22)&np.isfinite(z)
    if min(core.sum(),rim.sum(),outer.sum()) < 4:
        return dict(source=url,reason="insufficient measured floor, rim or exterior")
    a=np.deg2rad(angle)
    plane=np.stack([np.ones(z.shape),r*np.sin(a),r*np.cos(a)],axis=-1)
    residual=z-plane@np.linalg.lstsq(plane[outer],z[outer],rcond=None)[0]
    floor=np.median(residual[core])
    sectors=((angle+180)/45).astype(int)%8
    heights=[np.median(residual[rim&(sectors==k)]) for k in range(8) if (rim&(sectors==k)).any()]
    if len(heights)<6:
        return dict(source=url,reason="insufficient observed rim sectors")
    return dict(source=url, features=[float((np.median(heights)-floor)/radius),
                float(np.median(heights)/radius),float(np.mean(heights>floor))])


def run(sites, out):
    data=list(csv.DictReader(sites.open()))
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",GDAL_HTTP_MAX_RETRY="3",GDAL_HTTP_TIMEOUT="30",
                      CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif"):
        for s in data:
            s.update(sample_site(s))
            print(s["site"],flush=True)
    train=[s for s in data if s["partition"]=="fit" and "features" in s]
    X=np.asarray([s["features"] for s in train]); y=np.array([int(s["label"]) for s in train])
    mean=X.mean(axis=0); scale=X.std(axis=0); scale[scale==0]=1
    design=np.column_stack([np.ones(len(X)), (X-mean)/scale])
    def loss(b):
        logits=design@b
        return np.sum(np.logaddexp(0,logits)-y*logits)+.5*(b[1:]@b[1:])
    fit=minimize(loss,np.zeros(design.shape[1]),method="BFGS")
    if not fit.success:raise RuntimeError(fit.message)
    counts=dict(tp=0,fn=0,tn=0,fp=0,unscored_positive=0,unscored_negative=0)
    for s in data:
        label=int(s["label"])
        if "features" in s:
            logit=fit.x[0]+((np.array(s["features"])-mean)/scale)@fit.x[1:]
            s["rank_score"]=float(expit(logit))
        if s["partition"]=="evaluation":
            if "features" not in s: key="unscored_positive" if label else "unscored_negative"
            elif s["rank_score"]>=.5:key="tp" if label else "fp"
            else:key="fn" if label else "tn"
            counts[key]+=1
    out.write_text(json.dumps(dict(features=FEATURES,coefficients=fit.x.tolist(),mean=mean.tolist(),
        scale=scale.tolist(),threshold=.5,train_count=len(train),evaluation=counts,sites=data,
        scope="Known centres and diameters supplied. Australia withheld from fitting. Review labels are morphological. No archaeological or discovery accuracy inferred."),indent=2))


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("sites",type=Path);p.add_argument("out",type=Path)
    a=p.parse_args();run(a.sites,a.out)
