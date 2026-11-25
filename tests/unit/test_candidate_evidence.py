import numpy as np

from palimpsest.detector import detect_candidates


def test_density_floor_and_modern_land_use_on_the_same_pad():
    """An otherwise detectable pad needs measured ground, canopy and road clearance."""
    y, x = np.mgrid[:201, :201] * 0.5
    radius = np.hypot(x - 50, y - 50)
    blend = np.clip((radius - 7) / 3, 0, 1)
    ground = (100 + blend * (x - 50) * 0.45).astype("f4")
    canopy = np.full_like(ground, 14)
    density = np.full_like(ground, 3)
    layers = {
        "lrm": ground - (100 + (x - 50) * 0.45),
        "upslope_area_m2": np.ones_like(ground),
        "drainage_violation": np.zeros_like(ground),
    }

    def detect(chm, rho, features=None):
        return detect_candidates(ground, chm, rho, layers, osm_vectors=features)

    assert any(c.morphology == "terrace" for c in detect(canopy, density).survivors)
    assert not detect(np.full_like(canopy, 1.4), density).survivors
    track = [{"type": "node", "id": 1, "x": 60, "y": 50,
              "tags": {"highway": "track", "historic": "road"}}]
    blocked = detect(canopy, density, track)
    assert not blocked.survivors
    assert any(c.osm_match == "highway=track" for c in blocked.candidates)

    density[radius < 10] = 0.49
    assert not detect(canopy, density).survivors


def test_independent_ground_returns_must_agree_with_feature_elevation(monkeypatch):
    from types import SimpleNamespace

    from palimpsest import provenance

    terrain = SimpleNamespace(dtm=np.zeros((40, 40)), x0=0., y0=0., dx=.5)
    candidate = SimpleNamespace(x_6676=10., y_6676=10., area_m2=25.)
    x, y = np.mgrid[8:12:.5, 8:12:.5]
    xyz = np.column_stack((x.ravel(), y.ravel(), np.zeros(x.size), np.full(x.size, 2)))
    monkeypatch.setattr(provenance, "_cloth_ground_indices", lambda pts, params: np.arange(len(pts)))
    assert provenance._independent_density(candidate, [xyz], terrain)[0] >= .5
    xyz[:, 2] += 4.
    assert provenance._independent_density(candidate, [xyz], terrain)[0] == 0.
