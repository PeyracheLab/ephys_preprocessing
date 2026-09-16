"""
file_utils.py
=============
Moves ancillary files into the final merged output folder.

Handles:
  - Epoch_TS.csv
  - per-session _analogin.dat  → merged/<merge>_00_analogin.dat, _01_, … (kept separate)
  - per-session _digitalin.dat → merged/<merge>_00_digitalin.dat, _01_, … (kept separate)
  - per-session _auxiliary.dat → concatenated into merged/<merge>_auxiliary.dat
  - per-session position .csv  → merged/<merge>_N.csv
  - first-session .nrs         → merged/<merge>.nrs
"""

import platform
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional

from . import config as cfg


def move_ancillary_files(
    rec_list: List[str],
    merge_name: str,
    epoch_path: Path,
    data_dir: Optional[Path] = None,
    dry_run: bool = False,
    keep_analogin: bool = True,
    keep_digitalin: bool = True,
    keep_auxiliary: bool = True,
) -> None:
    """
    Move / copy all ancillary files into the final <merge_name> folder.

    Parameters
    ----------
    rec_list       : ordered list of per-session basenames
    merge_name     : name of the final output folder / file base
    epoch_path     : path to the already-generated Epoch_TS.csv
    data_dir       : working directory (default: cwd)
    dry_run        : if True, print without acting
    keep_analogin  : copy per-session analogin files into the merge folder
    keep_digitalin : copy per-session digitalin files into the merge folder
    keep_auxiliary : concatenate auxiliary files into the merge folder
    """
    if data_dir is None:
        data_dir = Path.cwd()

    out_dir = data_dir / merge_name

    # ── Epoch_TS.csv ───────────────────────────────────────────────────────
    _move(epoch_path, out_dir / "Epoch_TS.csv", dry_run)

    # ── Per-session position csv files ────────────────────────────────────
    for ii, rec in enumerate(rec_list):
        _move_session_file(
            data_dir / f"{rec}.csv",
            out_dir  / f"{merge_name}_{ii}.csv",
            dry_run)

    # ── Analogin: keep each session as a separate numbered file ───────────
    if keep_analogin:
        for ii, rec in enumerate(rec_list):
            src = data_dir / rec / f"{rec}_analogin.dat"
            dst = out_dir / f"{merge_name}_{ii}_analogin.dat"
            if dry_run:
                if src.exists():
                    print(f"    [dry] COPY  {src.name}  →  {dst.name}")
            else:
                _copy_if_exists(src, dst)

    # ── Digitalin: keep each session as a separate numbered file ──────────
    if keep_digitalin:
        for ii, rec in enumerate(rec_list):
            src = data_dir / rec / f"{rec}_digitalin.dat"
            dst = out_dir / f"{merge_name}_{ii}_digitalin.dat"
            if dry_run:
                if src.exists():
                    print(f"    [dry] COPY  {src.name}  →  {dst.name}")
            else:
                _copy_if_exists(src, dst)

    # ── Auxiliary: concatenate all sessions → single file ──────────────────
    if keep_auxiliary:
        aux_sources = []
        for rec in rec_list:
            src = data_dir / rec / f"{rec}_auxiliary.dat"
            if src.exists():
                aux_sources.append(src)

        if aux_sources:
            dst_aux = out_dir / f"{merge_name}_auxiliary.dat"
            if dry_run:
                print(f"    [dry] Concatenate {len(aux_sources)} auxiliary files → {dst_aux.name}")
            else:
                _cat_files(aux_sources, dst_aux)

    # ── .nrs: use the first session's file, rename to merge_name.nrs ─────
    for rec in rec_list:
        nrs_src = data_dir / f"{rec}.nrs"
        if nrs_src.exists():
            _move_session_file(nrs_src, out_dir / f"{merge_name}.nrs", dry_run)
            break   # only one .nrs needed

    # ── Move the merged .dat into output folder ────────────────────────────
    _move(data_dir / f"{merge_name}.dat",
          out_dir  / f"{merge_name}.dat",
          dry_run)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _copy_if_exists(src: Path, dst: Path) -> None:
    if not src.exists():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def _move(src: Path, dst: Path, dry_run: bool) -> bool:
    if not src.exists():
        return False
    if dry_run:
        print(f"    [dry] MOVE  {src.name}  →  {dst}")
        return True
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    return True


def _move_session_file(src: Path, dst: Path, dry_run: bool) -> None:
    """Move only if the source exists; warn but don't fail if missing."""
    if not _move(src, dst, dry_run):
        pass   # silently skip missing ancillary files


def _cat_files(src_files: List[Path], dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if platform.system() != "Windows" and len(src_files) > 1:
        cmd = ["cat"] + [str(f) for f in src_files]
        with open(dst, "wb") as out:
            subprocess.run(cmd, stdout=out, check=True)
    else:
        with open(dst, "wb") as fout:
            for src in src_files:
                with open(src, "rb") as fin:
                    shutil.copyfileobj(fin, fout)
