"""Scan one metric airborne LiDAR footprint with a 50 m halo and export survey-native evidence."""
import argparse
import hashlib
import json
import tempfile
from dataclasses import replace
from pathlib import Path

import laspy
import numpy as np
from pyproj import CRS, Transformer

from palimpsest.coverage import write_density_map
from palimpsest.detector import detect_candidates
from palimpsest.lidar import stream_study_zone, _peak_rss_gb
from palimpsest.provenance import confirm_raw_ground


def checksum(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def scan(source, epsg, bounds, out, source_ref):
    crs = CRS.from_epsg(epsg)
    if not crs.is_projected or any(a.unit_conversion_factor != 1 for a in crs.axis_info[:2]):
        raise ValueError("Supply a projected horizontal CRS in metres and elevations in metres.")
    x, y, east, north = bounds
    if not (0 < east-x <= 300 and 0 < north-y <= 300):
        raise ValueError("Choose a positive core up to 300 × 300 m per run.")
    halo = 50
    rect = [x-halo, y-halo, east+halo, north+halo]
    out.mkdir(parents=True, exist_ok=True)
    manifest = out/"scan.json"
    if any(out.iterdir()):
        raise FileExistsError(f"Use an empty output directory: {out}")
    with tempfile.TemporaryDirectory(prefix="palim-regional-") as name:
        tmp = Path(name)
        (tmp/"lidar").mkdir()
        with laspy.open(source) as f:
            header_crs = f.header.parse_crs()
            if header_crs and header_crs.to_2d() != crs.to_2d():
                raise ValueError("Supplied CRS disagrees with LAS header")
            if np.any(f.header.mins[:2] > np.array(rect[:2]) + .5) or np.any(f.header.maxs[:2] < np.array(rect[2:]) - .5):
                raise ValueError("Core plus halo must lie inside the source tile")
            count = 0
            with laspy.open(tmp/"lidar/clip.las", mode="w", header=f.header) as writer:
                for points in f.chunk_iterator(250000):
                    xx, yy = np.asarray(points.x), np.asarray(points.y)
                    mask = (xx>=rect[0]) & (yy>=rect[1]) & (xx<rect[2]) & (yy<rect[3])
                    count += int(mask.sum())
                    if count > 5500000:
                        raise ValueError("Reduce the core dimensions for this point density")
                    if mask.any():
                        writer.write_points(points[mask])
        if not count:
            raise ValueError("No returns in requested footprint")
        # Derive bounds from the explicit rectangle, including sparse margins.
        (tmp/"study_zone.json").write_text(json.dumps(dict(epsg=epsg, bounds_epsg6676=rect)))
        g = stream_study_zone(tmp)
        # Model geometry is translation invariant. The frozen detector's Japan-specific
        # geographic/temporal fields are discarded. Raw confirmation uses native XY.
        detections = detect_candidates(g.dtm, g.chm, g.rho_gnd, {}, dx=g.dx)
        for c in detections.candidates:
            c.x_6676 += g.x0
            c.y_6676 += g.y0
        confirm_raw_ground(detections, g, tmp)
        to_geo = Transformer.from_crs(crs, 4326, always_xy=True)
        features = []
        for c in detections.survivors:
            if x<=c.x_6676<east and y<=c.y_6676<north:
                lon, lat = to_geo.transform(c.x_6676,c.y_6676)
                features.append(dict(type="Feature",geometry=dict(type="Point",coordinates=[lon,lat]),
                    properties=dict(morphology=c.morphology,wall_height_m=c.wall_height_m,
                    mean_footprint_density=c.mean_rho_gnd,q_value=c.q_value,interpretation="unreviewed terrain lead")))
        trim = int(halo/g.dx)
        sl = np.s_[trim:-trim,trim:-trim]
        core = replace(g,x0=x,y0=y,**{k:getattr(g,k)[sl] for k in ("dtm","dsm","chm","rho_gnd")})
        write_density_map(out,core)
        (out/"leads.geojson").write_text(json.dumps(dict(type="FeatureCollection",features=features),allow_nan=False))
        peak = _peak_rss_gb()*1024**3/1e9
        if peak >= 4:
            raise MemoryError(f"Regional scan exceeded 4 GB ({peak:.3f} GB)")
        summary = dict(source=source_ref,source_file_sha256=checksum(source),epsg=epsg,core_bounds=bounds,
                       halo_m=halo,returns_including_halo=count,cell_m=g.dx,core_area_m2=(east-x)*(north-y),
                       supported_area_m2=float((core.rho_gnd>=.5).sum()*g.dx**2),leads=len(features),
                       peak_decimal_gb=peak,interpretation="Exploratory. Raw confirmation required. Local sensitivity, modern land use and chronology unassessed.")
        manifest.write_text(json.dumps(summary,indent=2))
        return summary


if __name__ == "__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("source",type=Path)
    p.add_argument("--source-ref",required=True)
    p.add_argument("--epsg",type=int,required=True)
    p.add_argument("--bounds",nargs=4,type=int,required=True)
    p.add_argument("--out",type=Path,required=True)
    a=p.parse_args()
    print(json.dumps(scan(a.source,a.epsg,a.bounds,a.out,a.source_ref),indent=2))
