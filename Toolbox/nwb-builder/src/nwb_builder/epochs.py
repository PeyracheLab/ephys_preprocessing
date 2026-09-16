"""Parse Epoch_TS.csv into epoch boundaries.

Format observed in the data (one epoch per line, no header, no index column):

    0.000000,635.544000

or for a multi-epoch day:

    0.000000,610.308000
    610.308000,1252.476000

Each row is `<start_seconds>,<end_seconds>`. Start/end are already expressed
in the global clock of the session's main .dat file (i.e. epoch i+1's start
equals epoch i's end for a contiguous recording).
"""
from __future__ import annotations

import glob
import os
from dataclasses import dataclass


@dataclass
class Epoch:
    index: int  # 0-based
    start: float  # seconds, global/session clock
    end: float  # seconds, global/session clock
    label: str


def find_epoch_ts(session_dir: str) -> str:
    matches = glob.glob(os.path.join(session_dir, "Epoch_TS.csv"))
    if not matches:
        # fall back to case-insensitive search
        matches = [
            os.path.join(session_dir, f)
            for f in os.listdir(session_dir)
            if f.lower() == "epoch_ts.csv"
        ]
    if not matches:
        raise FileNotFoundError(f"No Epoch_TS.csv found in {session_dir}")
    return matches[0]


def parse_epoch_ts(session_dir: str, labels: list[str] | None = None) -> list[Epoch]:
    path = find_epoch_ts(session_dir)
    epochs: list[Epoch] = []
    with open(path, "r") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line:
                continue
            start_str, _, end_str = line.partition(",")
            start_str = start_str.strip()
            end_str = end_str.strip()
            if not start_str or not end_str:
                continue
            idx0 = len(epochs)
            label = labels[idx0] if labels and idx0 < len(labels) else f"epoch{idx0}"
            epochs.append(Epoch(index=idx0, start=float(start_str), end=float(end_str), label=label))

    if not epochs:
        raise ValueError(f"No valid epoch rows parsed from {path}")
    return epochs
