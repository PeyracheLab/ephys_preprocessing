"""
concatenate.py
==============
Port of Process_ConcatenateDatFiles.m

Concatenates multiple flat int16 binary .dat files into a single output file.
Uses chunked streaming so arbitrarily large files can be handled without
loading everything into RAM.

The MATLAB original used OS-level  cat / copy /B  commands.
We do the same thing in pure Python for cross-platform compatibility,
with an optional fast path that shells out to `cat` on Unix.
"""

import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List

from . import config as cfg


def concatenate_dat_files(
    rec_list: List[str],
    merge_name: str,
    data_dir: Path | None = None,
    dry_run: bool = False,
) -> Path:
    """
    Concatenate  rec_list[i].dat  files into  merge_name.dat .

    Parameters
    ----------
    rec_list   : ordered list of basename strings (e.g. ['KMM43-260311-01', ...])
    merge_name : output basename            (e.g. 'KMM43-260311')
    data_dir   : directory containing the .dat files (default: cwd)
    dry_run    : if True, print actions without writing

    Returns
    -------
    Path to the merged .dat file.
    """
    if data_dir is None:
        data_dir = Path.cwd()

    src_files = [data_dir / f"{r}.dat" for r in rec_list]
    dst_file  = data_dir / f"{merge_name}.dat"

    # ── Validation ─────────────────────────────────────────────────────────
    if not dry_run:
        missing = [str(f) for f in src_files if not f.exists()]
        if missing:
            raise FileNotFoundError(
                f"The following .dat files are missing:\n  " + "\n  ".join(missing))

    if dry_run:
        total_mb = sum(f.stat().st_size for f in src_files if f.exists()) / 1e6
        print(f"    [dry] Would concatenate {len(src_files)} file(s) → {dst_file.name}")
        print(f"    [dry] Estimated output size: {total_mb:.1f} MB")
        return dst_file

    # ── Fast path: shell out to `cat` on Unix ──────────────────────────────
    if platform.system() != "Windows" and len(src_files) > 1:
        _cat_unix(src_files, dst_file)
    else:
        _cat_python(src_files, dst_file)

    size_gb = dst_file.stat().st_size / 1e9
    print(f"      Merged {len(src_files)} file(s) → {dst_file.name}  ({size_gb:.2f} GB)")
    return dst_file


def _cat_unix(src_files: List[Path], dst_file: Path) -> None:
    """Shell out to cat for maximum speed on Linux/macOS."""
    cmd = ["cat"] + [str(f) for f in src_files]
    with open(dst_file, "wb") as out:
        subprocess.run(cmd, stdout=out, check=True)


def _cat_python(src_files: List[Path], dst_file: Path) -> None:
    """
    Pure-Python streaming concatenation.
    Reads CONCAT_CHUNK_SAMPLES * n_channels * 2 bytes at a time.
    (n_channels unknown here, so we use a fixed byte chunk size.)
    """
    chunk_bytes = cfg.CONCAT_CHUNK_SAMPLES * 2   # int16 = 2 bytes, channels merged later

    if len(src_files) == 1:
        shutil.copy2(src_files[0], dst_file)
        return

    with open(dst_file, "wb") as fout:
        for src in src_files:
            with open(src, "rb") as fin:
                while True:
                    buf = fin.read(chunk_bytes)
                    if not buf:
                        break
                    fout.write(buf)


def concatenate_auxiliary_dat(
    rec_list: List[str],
    merge_name: str,
    data_dir: Path | None = None,
    dry_run: bool = False,
) -> Path | None:
    """
    Concatenate per-session auxiliary.dat files into a single merged auxiliary.
    These live inside the per-session sub-folders.
    """
    if data_dir is None:
        data_dir = Path.cwd()

    src_files = []
    for r in rec_list:
        candidate = data_dir / r / f"{r}_auxiliary.dat"
        if candidate.exists():
            src_files.append(candidate)

    if not src_files:
        return None

    dst = data_dir / f"{merge_name}_auxiliary.dat"
    if dry_run:
        print(f"    [dry] Would concatenate auxiliary: {len(src_files)} file(s) → {dst.name}")
        return dst

    if platform.system() != "Windows" and len(src_files) > 1:
        _cat_unix(src_files, dst)
    else:
        _cat_python(src_files, dst)

    return dst
