import sys
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

sys.path.insert(0, str(Path(__file__).parents[1]))

from feature_engineering.landcover import calculate_landcover_features


def test_worldcover_ratios_from_raster(tmp_path):
    raster_path = tmp_path / "worldcover.tif"
    values = np.array(
        [[10, 40, 50], [10, 40, 50], [20, 40, 50]],
        dtype="uint8",
    )
    with rasterio.open(
        raster_path,
        "w",
        driver="GTiff",
        height=3,
        width=3,
        count=1,
        dtype="uint8",
        crs="EPSG:4326",
        transform=from_origin(77.0, 28.01, 0.001, 0.001),
    ) as dataset:
        dataset.write(values, 1)

    result = calculate_landcover_features(
        {"latitude": 28.008, "longitude": 77.001},
        raster_path,
    )

    assert result["forest_ratio"] == pytest.approx(1 / 3)
    assert result["agriculture_ratio"] == pytest.approx(1 / 3)
    assert result["builtup_ratio"] == pytest.approx(1 / 3)
    assert result["industrial_ratio"] is None
