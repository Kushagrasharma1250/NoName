import json
import os
from pathlib import Path

import numpy as np

try:
    import rasterio
    from rasterio.warp import transform
except ImportError:  # pragma: no cover - dependency is declared in requirements.txt
    rasterio = None
    transform = None


DEFAULT_CLASS_MAPPING = {
    "forest": [10, 20, 30],
    "agriculture": [40],
    "builtup": [50],
    "industrial": [],
}


def _class_mapping() -> dict[str, list[int]]:
    raw_mapping = os.getenv("LANDCOVER_CLASS_MAPPING")
    if not raw_mapping:
        return DEFAULT_CLASS_MAPPING
    try:
        configured = json.loads(raw_mapping)
    except json.JSONDecodeError as error:
        raise ValueError("LANDCOVER_CLASS_MAPPING must be valid JSON") from error
    return {
        category: [int(value) for value in configured.get(category, classes)]
        for category, classes in DEFAULT_CLASS_MAPPING.items()
    }


def _raster_path(raster_path: str | Path | None = None) -> Path | None:
    configured_path = raster_path or os.getenv("LANDCOVER_RASTER_PATH")
    return Path(configured_path) if configured_path else None


def _window_values(dataset, latitude: float, longitude: float) -> np.ndarray:
    x, y = transform("EPSG:4326", dataset.crs, [longitude], [latitude])
    row, column = dataset.index(x[0], y[0])
    radius_m = float(os.getenv("LANDCOVER_RADIUS_M", "500"))
    pixel_size_x, pixel_size_y = dataset.res
    if dataset.crs.is_geographic:
        meters_per_degree = 111_320
        radius_columns = max(
            1,
            int(radius_m / (meters_per_degree * max(abs(np.cos(np.radians(latitude))), 0.01) * abs(pixel_size_x))),
        )
        radius_rows = max(1, int(radius_m / (meters_per_degree * abs(pixel_size_y))))
    else:
        radius_columns = max(1, int(radius_m / abs(pixel_size_x)))
        radius_rows = max(1, int(radius_m / abs(pixel_size_y)))
    window = rasterio.windows.Window(
        column - radius_columns,
        row - radius_rows,
        radius_columns * 2 + 1,
        radius_rows * 2 + 1,
    )
    values = dataset.read(1, window=window, boundless=True, masked=True)
    return np.asarray(values.compressed())


def calculate_landcover_features(event, raster_path: str | Path | None = None):
    path = _raster_path(raster_path)
    empty_features = {
        "industrial_ratio": None,
        "forest_ratio": None,
        "agriculture_ratio": None,
        "builtup_ratio": None,
    }
    if path is None:
        return empty_features
    if rasterio is None:
        raise RuntimeError("rasterio is required for raster-backed land-cover features")
    if not path.exists():
        raise FileNotFoundError(f"Land-cover raster does not exist: {path}")

    with rasterio.open(path) as dataset:
        values = _window_values(
            dataset,
            float(event["latitude"]),
            float(event["longitude"]),
        )

    if not len(values):
        return empty_features

    mapping = _class_mapping()
    total_pixels = len(values)
    features = {}
    for category, classes in mapping.items():
        features[f"{category}_ratio"] = (
            None
            if not classes
            else round(float(np.isin(values, classes).sum() / total_pixels), 6)
        )
    return features
