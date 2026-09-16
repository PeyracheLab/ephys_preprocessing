"""
intan_info.py
=============
Minimal reader for Intan RHD2000 info.rhd files.

Currently exposes only read_sample_rate(), which reads the first 12 bytes of
the file (magic + version + sample_rate).  That scalar is unambiguous and does
not require parsing the full channel list.

Channel grouping is NOT inferred from info.rhd — use the Neuroscope XML or a
probe.json supplied by the user.
"""

import struct
from pathlib import Path

_MAGIC = 0xC6912702


def read_sample_rate(path: "Path | str") -> float:
    """
    Read the recording sample rate from an Intan RHD2000 info.rhd file.

    Reads only the first 12 bytes:
        bytes 0-3   : magic number (uint32 LE)
        bytes 4-5   : version major (int16 LE)
        bytes 6-7   : version minor (int16 LE)
        bytes 8-11  : sample rate  (float32 LE)

    Raises
    ------
    ValueError  if the magic number is wrong (not an RHD2000 file)
    OSError     if the file cannot be opened
    """
    path = Path(path)
    with open(path, 'rb') as f:
        magic = struct.unpack('<I', f.read(4))[0]
        if magic != _MAGIC:
            raise ValueError(f"Not a valid RHD2000 info file: {path}")
        f.read(4)   # skip version (2 × int16)
        return struct.unpack('<f', f.read(4))[0]
