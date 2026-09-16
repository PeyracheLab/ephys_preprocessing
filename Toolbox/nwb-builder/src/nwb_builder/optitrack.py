"""Load Optitrack-exported tracking CSVs (same layout nwbmatic expects:
header rows 4-5 give ('Position'|'Rotation', axis), data column 1 is
'Time (Seconds)')."""
from __future__ import annotations

import re

import numpy as np
import pandas as pd


def parse_capture_frame_rate(csv_file: str, default: float = 120.0) -> float:
    with open(csv_file, "r") as f:
        header = f.readline()
    m = re.search(r"Capture Frame Rate,([0-9.]+)", header)
    if m:
        return float(m.group(1))
    return default


def parse_capture_start_time(csv_file: str):
    """Best-effort parse of the 'Capture Start Time' field in the CSV header.
    Returns a naive datetime.datetime or None if it can't be parsed."""
    import datetime

    with open(csv_file, "r") as f:
        header = f.readline()
    m = re.search(r"Capture Start Time,([^,]+ [AP]M)", header)
    if not m:
        return None
    raw = m.group(1).strip()
    for fmt in ("%Y-%m-%d %I.%M.%S.%f %p", "%Y-%m-%d %I:%M:%S.%f %p"):
        try:
            return datetime.datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def load_optitrack_csv(csv_file: str) -> pd.DataFrame:
    """Load tracking data exported by Motive/Optitrack.

    Reads rows 4 and 5 (0-indexed) to build the column MultiIndex, and column
    1 ('Time (Seconds)') as the row index. Returns a DataFrame with columns
    x, y, z, rx, ry, rz (whichever are present), index = seconds from the
    start of this recording (local clock, to be re-aligned via TTL).
    """
    position = pd.read_csv(csv_file, header=[4, 5], index_col=1)
    if 1 in position.columns:
        position = position.drop(labels=1, axis=1)
    position = position[~position.index.duplicated(keep="first")]

    order = []
    cols = []
    for n in position.columns:
        if n[0] == "Rotation":
            order.append("r" + n[1].lower())
            cols.append(n)
        elif n[0] == "Position":
            order.append(n[1].lower())
            cols.append(n)
    if len(order) == 0:
        raise RuntimeError(f"Unknown tracking format for csv file {csv_file}")

    position = position[cols]
    position.columns = order

    # degrees -> radians, wrapped to [0, 2*pi)
    rot_cols = [c for c in ("rx", "ry", "rz") if c in position.columns]
    if rot_cols:
        position[rot_cols] = position[rot_cols].astype(float) * np.pi / 180.0
        position[rot_cols] = (position[rot_cols] + 2 * np.pi) % (2 * np.pi)

    return position
