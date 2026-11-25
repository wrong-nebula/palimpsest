"""A location hit can have the wrong morphology, and raw blackout overrides context."""
import numpy as np
import rasterio
from rasterio.transform import from_origin

from palimpsest.blind_trial import save
from palimpsest.paired_trial import summarize


def test_correct_class_and_supported_alert_rate_have_separate_denominators(tmp_path):
    with rasterio.open(tmp_path/"ground_coverage.tif", "w", driver="GTiff", width=3,
                       height=1, count=1, dtype="uint8", crs="EPSG:6676",
                       transform=from_origin(10, 20, .5, .5)) as raster:
        raster.write(np.array([[0, 3, 3]], dtype=np.uint8), 1)
    sites = [dict(id="a", kind="terrace", band=2), dict(id="b", kind="mound_pit", band=2)]
    save(tmp_path/"unsealed_truth.json", dict(sites=sites))
    alerts = [dict(outcome="target", band=2, kind="terrace", site=site) for site in ("a", "b")]
    alerts += [dict(outcome="novel", x=x, y=19.75) for x in (10.25,10.75)]
    save(tmp_path/"results.json", dict(alerts=alerts, bands=[dict(band=str(i)) for i in range(5)]))
    scored = summarize(tmp_path)["2"]
    assert scored["correct_class"] == 1
    assert scored["class_counts"]["mound_pit"] == {"correct":0,"total":1}
    assert scored["support_km2"] == 0.5 / 1e6
    assert scored["novel_on_support"] == 1
