"""Parse <basename>.SleepState.states.mat (written by buzcode's SleepScoreMaster)
into per-state interval arrays.

MATLAB structure (see SleepScoreMaster.m):

    SleepState.ints.WAKEstate   Nx2 array, [start, end] seconds, session-global clock
    SleepState.ints.NREMstate   Nx2 array  (= "sws")
    SleepState.ints.REMstate    Nx2 array  (= "rem")

Same time base as Epoch_TS.csv (seconds from the merged .dat file's start), so
these can be added to the NWB file without any unit conversion.
"""
from __future__ import annotations

import glob
import os

import numpy as np
from scipy.io import loadmat

# MATLAB field name -> (short name used for the NWB TimeIntervals table)
_STATE_FIELDS = {
    "NREMstate": "sws",
    "REMstate":  "rem",
    "WAKEstate": "wake",
}


def find_sleep_states_mat(session_dir: str, basename: str) -> str | None:
    path = os.path.join(session_dir, f"{basename}.SleepState.states.mat")
    if os.path.exists(path):
        return path
    matches = glob.glob(os.path.join(session_dir, "*.SleepState.states.mat"))
    return matches[0] if matches else None


def load_sleep_states(session_dir: str, basename: str) -> dict[str, np.ndarray] | None:
    """
    Return {"sws": Nx2 array, "rem": Nx2 array, "wake": Nx2 array} in seconds,
    or None if no SleepState.states.mat is found for this session.
    """
    path = find_sleep_states_mat(session_dir, basename)
    if path is None:
        return None

    mat = loadmat(path, simplify_cells=True)
    if "SleepState" not in mat or "ints" not in mat["SleepState"]:
        raise ValueError(f"{path} does not contain a SleepState.ints struct")

    ints = mat["SleepState"]["ints"]
    states: dict[str, np.ndarray] = {}
    for mat_field, short_name in _STATE_FIELDS.items():
        arr = np.asarray(ints.get(mat_field, np.empty((0, 2))), dtype=float)
        if arr.ndim == 1:
            arr = arr.reshape(0, 2) if arr.size == 0 else arr.reshape(1, 2)
        states[short_name] = arr
    return states
