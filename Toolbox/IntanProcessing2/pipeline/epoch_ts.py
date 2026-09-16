"""
epoch_ts.py
===========
Builds the Epoch_TS.csv file that records the start/end time (in seconds)
of each original recording session within the merged .dat file.

This is a direct port of the epoch-writing block in Process_RenameCopyIntan.m:

    epochs(ii,1) = start;
    start = start + durations(ii);
    epochs(ii,2) = start;
    dlmwrite('Epoch_TS.csv', epochs, 'precision', '%.6f');
"""

import csv
from pathlib import Path
from typing import List


def build_epoch_ts(
    durations: List[float],
    output_path: Path | None = None,
    dry_run: bool = False,
) -> Path:
    """
    Parameters
    ----------
    durations   : list of recording durations in seconds (one per session)
    output_path : where to write the file (default: cwd/Epoch_TS.csv)
    dry_run     : if True, print the table without writing

    Returns
    -------
    Path to the created (or would-be created) CSV file.
    """
    if output_path is None:
        output_path = Path.cwd() / "Epoch_TS.csv"

    epochs = []
    start = 0.0
    for dur in durations:
        end = start + dur
        epochs.append((start, end))
        start = end

    if dry_run:
        print(f"    [dry] Would write Epoch_TS.csv ({len(epochs)} rows):")
        for i, (s, e) in enumerate(epochs):
            print(f"          {i+1}: {s:.6f}  {e:.6f}")
        return output_path

    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)
        for s, e in epochs:
            writer.writerow([f"{s:.6f}", f"{e:.6f}"])

    return output_path
