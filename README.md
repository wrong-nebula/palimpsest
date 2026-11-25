# PALIMPSEST

[Open the terrain atlas](https://wrong-nebula.github.io/palimpsest/) · [Launch the regional CPU notebook](https://colab.research.google.com/github/wrong-nebula/palimpsest/blob/main/notebooks/regional_scan.ipynb)

PALIMPSEST reconstructs bare terrain from airborne LiDAR, records ground-return support, and tests terrace, mound/pit and transverse ridge-cut profiles. The public atlas includes a WebGPU bench with three representative packs and a coverage map for the full Takatenjin West Ridge basin.

## What a detection means

On the two most recent blinded Shizuoka tiles, the frozen detector recovered one of twenty injected features. It missed all six pits and all six terraces, flagged one new background location, and triggered on zero of eleven forestry-track decoys. Use it to inspect terrain and prioritize field visits. The local ground-support gate excludes interpolated holes. The density bands describe observations. Sensitivity in a new region needs independent measurement. [Results by tile, morphology and density](docs/bench/data/paired_trial/comparison.json)

## Regional scan

The Colab notebook downloads a checksummed public swisstopo tile, clips a small core with a 50 m halo, streams the raw returns through cloth filtering, checks detections against raw ground elevations, and exports GeoTIFF coverage, GeoJSON leads, and survey provenance. Run one footprint per output directory. The international adapter uses the source survey's projected metre CRS. Historical classes, map falsifiers and regional accuracy estimates require local evidence.

The Swiss example was executed on both a Colab CPU and the local workstation. Both runs read the same LAS checksum, processed 1,418,300 returns including the halo, found 55,351.75 m² above the local support threshold, and returned zero leads. Colab peak process RSS was 0.809 decimal GB. [Colab run record](docs/bench/data/swiss_pilot/colab.json)

For local use, install the packages in requirements-pilot.txt with Python 3.11 or newer. With a LAS or LAZ file and its documented horizontal CRS, vertical metre units and bounds, run:

```sh
python -m palimpsest.regional_pilot tile.las --epsg 2056 \
  --bounds 2598280 1202700 2598520 1202940 --source-ref survey-record-url --out regional-result
```

## Crater training

The crater experiment uses a separate logistic ranker over dimensionless relief and rim closure. Measurements come from native Copernicus GLO-30 pixels at labeled reference centres and supplied diameters. Thirteen non-Australian sites were used for fitting. At the fixed score threshold, the Australian evaluation flagged two of three catalogued impacts and all seven reviewed look-alikes. The labels for mines, valleys and sand-ridge hollows are visual assessments. This test measures classification at supplied locations. It provides no blind discovery rate or archaeological training labels. [Site labels](experiments/craters/sites.csv) · [Measurements and fitted coefficients](experiments/craters/result.json)

```sh
python -m palimpsest.crater_pilot experiments/craters/sites.csv crater-result.json
```

## Site build

The published static files are in `docs/`. To regenerate from a full local research workspace, build the TypeScript viewer with `npm ci && npm run build` inside `viewer/`, then run `python -m palimpsest.pages docs` from the root. The build reads the full basin export and evaluation outputs under `data/output/`. The published repository distributes the compact atlas. Original LiDAR inputs and the full pack archive are separately held in the research workspace.

Shizuoka elevation data are from VIRTUAL SHIZUOKA, aerial imagery from GSI Japan, and mapped features from © OpenStreetMap contributors. The Swiss example uses swissSURFACE3D (© swisstopo). Elevation measurements for the crater experiment use the Copernicus DEM GLO-30, accessed from the [Registry of Open Data](https://registry.opendata.aws/copernicus-dem/). See the survey links and measured results in the atlas.
