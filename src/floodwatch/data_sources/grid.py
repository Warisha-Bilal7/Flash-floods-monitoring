"""
Spatial 3x3 Grid Query Generator (grid.py)
==========================================
Generates multi-point spatial query coordinates centered on basin centroids
to feed the spatial branch of Model A (CNN-LSTM).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class GridCell:
    row_idx: int       # 0, 1, 2
    col_idx: int       # 0, 1, 2
    lat: float
    lon: float
    is_center: bool


def generate_3x3_patch_coords(
    center_lat: float,
    center_lon: float,
    resolution_deg: float = 0.10
) -> list[GridCell]:
    """
    Generates a 3x3 spatial grid centered at (center_lat, center_lon).
    Cells are ordered row-by-row (North to South, West to East):
      (lat + res, lon - res)  (lat + res, lon)  (lat + res, lon + res)
      (lat,       lon - res)  (lat,       lon)  (lat,       lon + res)
      (lat - res, lon - res)  (lat - res, lon)  (lat - res, lon + res)
    """
    cells: list[GridCell] = []
    lat_offsets = [resolution_deg, 0.0, -resolution_deg]
    lon_offsets = [-resolution_deg, 0.0, resolution_deg]

    for r, d_lat in enumerate(lat_offsets):
        for c, d_lon in enumerate(lon_offsets):
            is_center = (r == 1 and c == 1)
            cells.append(GridCell(
                row_idx=r,
                col_idx=c,
                lat=round(center_lat + d_lat, 4),
                lon=round(center_lon + d_lon, 4),
                is_center=is_center
            ))
    return cells


def assemble_spatial_tensor(
    cell_values: dict[tuple[int, int], np.ndarray],
    channels: list[str]
) -> np.ndarray:
    """
    Assembles a (C, 3, 3) spatial numpy array from dictionary of (row, col) feature vectors.
    """
    n_channels = len(channels)
    tensor = np.zeros((n_channels, 3, 3), dtype=np.float32)
    for (r, c), vals in cell_values.items():
        tensor[:, r, c] = vals[:n_channels]
    return tensor
