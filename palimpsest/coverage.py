"""Ground support for field interpretation. South-first model grids are exported north-up."""
from __future__ import annotations

import gzip
import json
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin
from scipy.ndimage import uniform_filter
from scipy.spatial import cKDTree

EDGES = (0.5, 1., 2.5, 5.)
LABELS = ("Blackout", "Below calibrated context", "0.5–<1", "1–<2.5", "2.5–<5", "≥5")
COLORS = ("#8d2745", "#555867", "#e7ad67", "#a9d3bf", "#56a69e", "#226471")
CALIBRATION_KEYS = ("[0.5, 1.0)", "[1.0, 2.5)", "[2.5, 5.0)", ">= 5.0")


def context_density(density, dx):
    """Use the calibration's 16 m square. Exclude off-map cells from the mean."""
    width = max(1, round(16 / dx))
    mean = uniform_filter(density, size=width, mode="constant", cval=0., output=np.float32)
    # The separable denominator counts only actual cells at study boundaries.
    weights = [uniform_filter(np.ones(n, np.float32), size=width, mode="constant") for n in density.shape]
    mean /= weights[0][:, None]
    mean /= weights[1][None, :]
    return mean


def coverage_codes(density, context):
    codes = np.searchsorted(EDGES, context, side="right").astype(np.uint8) + 1
    codes[~np.isfinite(context)] = 1
    codes[(density < EDGES[0]) | ~np.isfinite(density)] = 0
    return codes


def write_density_map(out, grid):
    context = context_density(grid.rho_gnd, grid.dx)
    codes = coverage_codes(grid.rho_gnd, context)
    with gzip.open(out / "ground_coverage.u8.gz", "wb", compresslevel=3) as fp:
        fp.write(memoryview(np.ascontiguousarray(codes)))
    ny, nx = codes.shape
    transform = from_origin(grid.x0, grid.y0 + ny * grid.dx, grid.dx, grid.dx)
    common = dict(driver="GTiff", width=nx, height=ny, transform=transform,
                  crs=f"EPSG:{grid.epsg}", compress="deflate", tiled=True)
    with rasterio.open(out / "ground_density.tif", "w", dtype="float32", count=2, predictor=3, **common) as ds:
        for i, (arr, name) in enumerate(((grid.rho_gnd, "Local CSF ground returns per square metre"),
                                         (context, "16 m square mean ground returns per square metre")), 1):
            ds.write(arr[::-1], i)
            ds.set_band_description(i, name)
    with rasterio.open(out / "ground_coverage.tif", "w", dtype="uint8", count=1, **common) as ds:
        ds.write(codes[::-1], 1)
        ds.set_band_description(1, "Density support with native blackout precedence")
        ds.write_colormap(1, {i: (*bytes.fromhex(c[1:]), 255) for i, c in enumerate(COLORS)})


def _blank_review_pair(grid, detection, codes, mean_rho, osm):
    """Choose adjacent examples with comparable canopy and no nearby exported waypoint."""
    if not detection.survivors:
        return []
    from shapely.geometry import Point

    tree = cKDTree([(c.x_6676, c.y_6676) for c in detection.survivors])
    step = max(1, round(16/grid.dx))
    ny, nx = codes.shape
    low, high = [], []
    # The widest profile needs 45 m of terrain around the centre.
    for row in range(4*step, ny-4*step, step):
        for col in range(4*step, nx-4*step, step):
            code = int(codes[ny-1-row, col])
            if code not in (2, 5):
                continue
            y, x = grid.y0+(row+.5)*grid.dx, grid.x0+(col+.5)*grid.dx
            chm = grid.chm[row-step//2:row+step//2,col-step//2:col+step//2]
            canopy = float(np.mean(chm))
            if not np.isfinite(canopy) or canopy < 5:
                continue
            gap = float(tree.query((x, y))[0])
            if gap <= 28:
                continue
            location = Point(x, y)
            if (osm.check_modern(location, 25) or osm.check_track(location, 25)
                    or osm.check_water(location, 20)):
                continue
            record = dict(x=x,y=y,code=code,mean_16m=float(mean_rho[ny-1-row,col]),
                          mean_chm_16m=canopy,nearest_survivor_m=gap)
            (low if code == 2 else high).append(record)
    if not low or not high:
        return []
    dense = cKDTree([(p["x"],p["y"]) for p in high])
    distance, neighbor = dense.query([(p["x"],p["y"]) for p in low],
                                     k=list(range(1, min(20, len(high))+1)))
    # Keep both letters legible on the printable overview.
    readable = np.where(distance >= 48, distance, np.inf)
    i, j = np.unravel_index(np.argmin(readable if np.isfinite(readable).any() else distance),
                            distance.shape)
    return [low[i],high[int(neighbor[i,j])]]


def write_candidate_support(out, grid, detection):
    """Attach unmasked review-window support to every catalog ID, including rejections."""
    ny, nx = grid.rho_gnd.shape
    width = max(1, round(16 / grid.dx))
    records = {}
    for c in detection.candidates:
        row, col = int((c.y_6676-grid.y0)/grid.dx), int((c.x_6676-grid.x0)/grid.dx)
        r, s = row-width//2, col-width//2
        window = grid.rho_gnd[max(0,r):min(ny,r+width), max(0,s):min(nx,s+width)]
        center = float(grid.rho_gnd[row,col])
        mean = float(np.mean(window, dtype=np.float64))
        counts = np.bincount(np.searchsorted(EDGES, window.ravel(), side="right"), minlength=5)
        records[c.candidate_id] = dict(x_6676=c.x_6676, y_6676=c.y_6676, center_rho=center,
                                       mean_16m=mean, window_cells=int(window.size),
                                       native_band_cells=counts.tolist())
    with rasterio.open(out/"ground_coverage.tif") as ds:
        north_first = ds.read(1)
        counts = np.bincount(north_first.ravel(), minlength=len(LABELS)).tolist()
        for record in records.values():
            row, col = ds.index(record["x_6676"], record["y_6676"])
            record["code"] = int(north_first[row, col])
    verify = out / "verify_tier2.json"
    calibration = None
    if verify.exists():
        report = json.loads(verify.read_text())
        if report["status"] == "PASS":
            calibration = report["results"]["tier2_soil_creep"]["recall_by_rho_gnd"]
    payload=dict(bounds=[grid.x0,grid.y0,grid.x0+nx*grid.dx,grid.y0+ny*grid.dx],dx=grid.dx,
                 epsg=grid.epsg,labels=LABELS,colors=COLORS,cell_counts=counts,
                 edges=EDGES, native_density_labels=("< 0.5", *CALIBRATION_KEYS),
                 context_window_m=16, density_units="CSF ground returns/m²",
                 viewer_grid=dict(file="ground_coverage.u8.gz",dtype="uint8",width=nx,height=ny,
                                  row_order="south to north",column_order="west to east"),
                 calibration=calibration,candidates=records)
    (out/"field_support.json").write_text(json.dumps(payload,ensure_ascii=False,indent=1)+"\n")



def finish_field_map(out, cache, detection=None):
    """Select negative review windows from the actual exported terrain cutouts."""
    import struct
    from types import SimpleNamespace
    from pyproj import Transformer
    from palimpsest.detector import _OSMIndex

    support = json.loads((out/"field_support.json").read_text())
    if detection is None:
        records = [SimpleNamespace(**c) for c in json.loads((out/"candidates.json").read_text())["candidates"]]
        detection = SimpleNamespace(candidates=records, survivors=[c for c in records if c.status=="survivor"])
    else:
        records = detection.candidates
    # Review is independent of the detector. Reapply only to the same location
    # and the same three georeferenced aerial crops.
    review_file = out/"imagery_review.json"
    if review_file.is_file():
        import hashlib
        by_location = {(c.x_6676,c.y_6676): c for c in records}
        for item in json.loads(review_file.read_text())["reviews"]:
            c = by_location.get((item["x_6676"], item["y_6676"]))
            if c is None or not c.pack_file:
                continue
            if all(c.textures.get(k) and hashlib.sha256((out/c.textures[k]).read_bytes()).hexdigest()==v
                   for k,v in item["texture_sha256"].items()):
                support["candidates"][c.candidate_id]["imagery_review"] = dict(
                    field_priority=item["field_priority"], notes=item["notes"])
    with rasterio.open(out/"ground_coverage.tif") as ds:
        codes = ds.read(1)
    west,south,*_ = support["bounds"]
    dx = support["dx"]
    canopy = np.full(codes.shape, np.nan, np.float32)
    for c in records:
        if not c.pack_file:
            continue
        with (out/c.pack_file).open("rb") as fp:
            _,_,nx,ny,x,y,step,*_ = struct.unpack("<4sIIIddfIIff12s",fp.read(64))
            fp.seek(64 + nx*ny*4)
            values = np.fromfile(fp, dtype="<f4", count=nx*ny).reshape(ny,nx)
            row,col = round((y-south)/dx),round((x-west)/dx)
            canopy[row:row+ny,col:col+nx] = values
    grid = SimpleNamespace(chm=canopy,dx=dx,x0=west,y0=south)
    osm_path = cache / "osm/osm_features.json"
    support["blank_examples"] = []
    if osm_path.is_file():
        osm = _OSMIndex(json.loads(osm_path.read_text()), Transformer.from_crs(4326, 6676, always_xy=True))
        with rasterio.open(out/"ground_density.tif") as ds:
            support["blank_examples"] = _blank_review_pair(grid, detection, codes, ds.read(2), osm)
    (out/"field_support.json").write_text(json.dumps(support,ensure_ascii=False,indent=1)+"\n")
    write_field_map(out, detection, support)


def write_field_map(out, detection, support, *, featured_id=None):
    import base64
    from html import escape
    from rasterio.enums import Resampling
    from rasterio.io import MemoryFile

    with rasterio.open(out/"ground_coverage.tif") as ds:
        w = min(1000, ds.width)
        h = round(ds.height*w/ds.width)
        codes = ds.read(1, out_shape=(h,w), resampling=Resampling.nearest)
    palette = np.array([list(bytes.fromhex(c[1:])) for c in COLORS],np.uint8)
    with MemoryFile() as mem:
        with mem.open(driver="PNG",width=w,height=h,count=3,dtype="uint8") as dst:
            dst.write(palette[codes].transpose(2,0,1))
        src = base64.b64encode(mem.read()).decode()
    x0,y0,x1,y1=support["bounds"]
    markers=[]
    focus=""
    for c in detection.survivors:
        x=(c.x_6676-x0)*w/(x1-x0); y=(y1-c.y_6676)*h/(y1-y0)
        markers.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="4.5" fill="white" stroke="#162436" stroke-width="1.6"><title>{escape(c.candidate_id)} · {escape(c.morphology)}</title></circle>')
        if c.candidate_id == featured_id:
            focus = f'''<g id="{escape(featured_id)}" transform="translate({x:.2f} {y:.2f})" class="focus-pin">
<title>Featured candidate {escape(featured_id)}</title>
<circle r="17" fill="none" stroke="#132b30" stroke-width="8"/><circle r="17" fill="none" stroke="#77ffeb" stroke-width="4"/>
<path d="M12 -12l25 -25h10" fill="none" stroke="#132b30" stroke-width="5"/>
<rect x="43" y="-53" width="120" height="31" rx="3" fill="#132b30"/>
<text x="103" y="-32" fill="white" text-anchor="middle" font-size="17">{escape(featured_id)}</text></g>'''
    density_link = ' · <a href="ground_density.tif">Density GeoTIFF</a>' if (out/"ground_density.tif").is_file() else ""
    examples=[]
    for letter, item in zip(("L","H"), support.get("blank_examples",[])):
        x=(item["x"]-x0)*w/(x1-x0);y=(y1-item["y"])*h/(y1-y0)
        examples.append(f'<g transform="translate({x:.1f} {y:.1f})"><title>{item["mean_16m"]:.2f} pts/m², no feature waypoint within {item["nearest_survivor_m"]:.0f} m</title><rect x="-11" y="-11" width="22" height="22" fill="#172d39" stroke="white"/><text text-anchor="middle" y="6" fill="white" font-size="18">{letter}</text></g>')
    example_caption = ("The squares L and H locate nearby forest review windows with low and higher support "
                       "and no waypoint within 28 m. " if examples else "")
    legend=[]
    desc=["Excluded from detection","Context below tested range"]+list(CALIBRATION_KEYS)
    for i,(label,col,n) in enumerate(zip(LABELS,COLORS,support["cell_counts"])):
        rr=(support["calibration"] or {}).get(desc[i])
        evidence=f"{rr['detected']}/{rr['total']} recovered" if rr else (desc[i] if i < 2 else "Calibration unavailable")
        legend.append(f'<tr><td><i style="background:{col}"></i>{escape(label)}</td><td>{n*support["dx"]**2/1e6:.3f}</td><td>{escape(evidence)}</td></tr>')
    catalog=[]
    for c in detection.candidates:
        ref=support["candidates"][c.candidate_id]
        blackout=100*ref["native_band_cells"][0]/ref["window_cells"]
        review = ref.get("imagery_review", {})
        disposition = review.get("field_priority", "Unreviewed")
        catalog.append(f'<tr><td>{escape(c.candidate_id)}</td><td>{escape(c.temporal_class)}</td><td>{escape(c.morphology)}</td><td>{ref["center_rho"]:.2f}</td><td>{ref["mean_16m"]:.2f}</td><td>{blackout:.1f}%</td><td>{escape(LABELS[ref["code"]])}</td><td>{escape(disposition)}</td></tr>')
    bar=250*w/(x1-x0)
    html=f'''<!doctype html><meta charset="utf-8"><link rel="icon" href="data:,"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Ground support · Takatenjin West Ridge</title>
<style>*{{box-sizing:border-box}}body{{margin:2rem auto;padding:0 1.5rem;max-width:1160px;color:#19313a;background:#faf9f5;font:16px/1.5 system-ui}}h1{{margin:0}}main{{display:grid;grid-template-columns:minmax(0,1.3fr) minmax(290px,1fr);gap:28px}}svg{{width:100%;border:1px solid #7a837e}}table{{border-collapse:collapse;width:100%}}td,th{{text-align:left;padding:6px 4px;border-bottom:1px solid #ddd}}i{{display:inline-block;width:1em;height:1em;margin-right:.5em}}@media(max-width:750px){{main{{display:block}}}}a{{color:#165e6a}}.focus-pin{{display:none}}.focus-pin:target{{display:inline}}</style>
<h1>Ground support on Takatenjin West Ridge</h1><p>Projected north up · JGD2011 / Japan Plane Rectangular CS VIII · EPSG:6676</p><main><section><svg viewBox="0 0 {w} {h}" aria-label="Basin ground support with field waypoints"><image width="{w}" height="{h}" href="data:image/png;base64,{src}"/><g id="pins">{''.join(markers)}{focus}</g>{''.join(examples)}<g fill="#152f38"><rect x="20" y="{h-50}" width="{bar+24}" height="36" fill="white"/><path d="M30 {h-25}h{bar}" stroke="black" stroke-width="4"/><text x="30" y="{h-33}" font-size="13">250 m</text></g></svg><label><input type="checkbox" checked onchange="document.getElementById('pins').style.display=this.checked?'':'none'"> Show field waypoints</label></section>
<section><h2>Reading a blank area</h2><p>White circles mark catalog survivors. {example_caption}A blank in the lowest tested band gives little evidence about buried relief. In the higher bands, “no detected feature” means the search saw ground and returned no candidate. Features can still be missed. Density measures ground observation. Open land, mapped infrastructure and other excluded settings can also have high ground density and a blank catalog.</p><table><thead><tr><th>Ground pts/m²</th><th>km²</th><th>Calibration sites</th></tr></thead>{''.join(legend)}</table>
<p>Blackout uses native local density below 0.5 pts/m². Other colors use the surrounding 16 m square mean. Band counts describe injections on four calibration tiles. They do not estimate the probability that any particular blank contains a site.</p><p>Bounds in metres, east {x0:.0f} to {x1:.0f}, north {y0:.0f} to {y1:.0f}. The overview samples the native grid for display.</p><p><a href="ground_coverage.tif">Native coverage GeoTIFF</a>{density_link} · <a href="field_support.json">Candidate support</a></p></section></main><details><summary>Ground support for all {len(catalog)} catalog records</summary><p>Local and 16 m mean densities are in pts/m². Blackout is the percentage of cells in the 16 m square below the local firewall.</p><table><tr><th>ID</th><th>Class</th><th>Shape</th><th>Local</th><th>16 m mean</th><th>Blackout</th><th>Map class</th><th>Photo review</th></tr>{''.join(catalog)}</table></details>'''
    (out/"coverage_map.html").write_text(html)
