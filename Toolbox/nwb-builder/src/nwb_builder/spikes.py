"""Load curated spike times from Neurosuite/Klusters .clu/.res files.

Cluster 0 = noise, cluster 1 = MUA/unsorted by Klusters convention; both are
dropped, matching nwbmatic. Spike times in .res are sample indices in the
session's global clock (same clock as the main .dat file and Epoch_TS.csv).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

import numpy as np


@dataclass
class SpikeData:
    # unit_id -> spike times in seconds (global clock)
    spike_times: dict[int, np.ndarray] = field(default_factory=dict)
    # unit_id -> 0-based shank/group index
    unit_group: dict[int, int] = field(default_factory=dict)


def load_neurosuite_spikes(session_dir: str, basename: str, fs: float) -> SpikeData:
    files = os.listdir(session_dir)
    clu_files = sorted(f for f in files if ".clu." in f and not f.startswith("."))
    res_files = sorted(f for f in files if ".res." in f and not f.startswith("."))

    clu_shanks = sorted(int(f.split(".")[-1]) for f in clu_files)
    res_shanks = sorted(int(f.split(".")[-1]) for f in res_files)
    if clu_shanks != res_shanks:
        raise RuntimeError(
            f"Mismatched .clu/.res shank files in {session_dir}: "
            f"clu={clu_shanks} res={res_shanks}"
        )

    result = SpikeData()
    count = 0
    for shank in clu_shanks:
        clu = np.genfromtxt(os.path.join(session_dir, f"{basename}.clu.{shank}"), dtype=np.int32)[1:]
        if clu.size == 0 or np.max(clu) <= 1:
            continue  # shank has no sorted units (only noise/MUA)

        res = np.genfromtxt(os.path.join(session_dir, f"{basename}.res.{shank}"))
        cluster_ids = np.unique(clu).astype(int)
        cluster_ids = cluster_ids[cluster_ids > 1]

        for cid in cluster_ids:
            t = res[clu == cid] / fs
            result.spike_times[count] = t
            result.unit_group[count] = shank - 1  # 0-based, matches group_to_channel
            count += 1

    return result
