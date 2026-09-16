"""Detect TTL sync pulses in a single-channel analogin.dat binary file.

Same peak-detection approach as nwbmatic.BaseLoader.load_ttl_pulse: normalize
the trace, find rising edges in the derivative, and use a minimum distance
derived from the camera frame rate to avoid double-counting noisy edges.
"""
from __future__ import annotations

import numpy as np
import scipy.signal


def load_ttl_pulse(
    ttl_file: str,
    tracking_frequency: float,
    n_channels: int = 1,
    channel: int = 0,
    bytes_size: int = 2,
    fs: float = 20000.0,
    threshold: float = 0.3,
) -> np.ndarray:
    """Return the local-clock timestamps (seconds, relative to the start of
    this analogin recording) of each detected TTL rising edge."""
    with open(ttl_file, "rb") as f:
        start = f.seek(0, 0)
        end = f.seek(0, 2)
    n_samples = int((end - start) / n_channels / bytes_size)

    with open(ttl_file, "rb") as f:
        data = np.fromfile(f, np.uint16).reshape((n_samples, n_channels))

    if n_channels == 1:
        data = data.flatten().astype(np.int32)
    else:
        data = data[:, channel].flatten().astype(np.int32)

    data = data / data.max()
    peaks, _ = scipy.signal.find_peaks(
        np.diff(data),
        height=threshold,
        distance=int(fs / (tracking_frequency * 2)),
    )
    timestep = np.arange(0, len(data)) / fs
    peaks += 1
    return timestep[peaks]
