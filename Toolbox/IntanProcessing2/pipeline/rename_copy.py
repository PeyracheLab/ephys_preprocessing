"""
rename_copy.py
==============
Port of Process_RenameCopyIntan.m

Discovers all session folders matching  AnimalID_YYMMDD_HHMMSS,
sorts them chronologically, and for each one:

  - Extracts the duration from time.dat  (4-byte int32 timestamps @ 20 kHz)
  - Renames / moves key files out of the session folder into flat files:
      AnimalID-YYMMDD-NN.dat         (amplifier data)
      AnimalID-YYMMDD-NN.xml         (parameter file)
      AnimalID-YYMMDD-NN/<files>     (analogin, digitalin, auxiliary, video, csv)

Returns
-------
rec_list   : list[str]   ordered basenames e.g. ['KMM43-260311-01', ...]
durations  : list[float] duration of each session in seconds
merge_name : str         e.g. 'KMM43-260311'
"""

import os
import re
import shutil
import warnings
from pathlib import Path
from typing import List, Tuple

from . import config as cfg


def _find_session_folders(animal_id: str, data_dir: Path) -> List[Tuple[int, str, Path]]:
    """
    Return list of (start_time_int, folder_name, folder_path) for all
    folders matching  AnimalID_YYMMDD_HHMMSS , sorted by start time.
    """
    pattern = re.compile(
        r"^" + re.escape(animal_id) + r"_(\d{6})_(\d{6})$"
    )
    hits = []
    for d in data_dir.iterdir():
        if not d.is_dir():
            continue
        m = pattern.match(d.name)
        if m:
            date_int  = int(m.group(1))
            time_int  = int(m.group(2))
            hits.append((date_int, time_int, d.name, d))

    if not hits:
        return []

    # Sort by date then time
    hits.sort(key=lambda x: (x[0], x[1]))

    # Derive merge_name from the first session's date
    first_date = hits[0][0]      # YYMMDD as int
    merge_name = f"{animal_id}-{first_date:06d}"

    return [(h[1], h[2], h[3]) for h in hits], merge_name


def _get_duration_from_time_dat(session_dir: Path, sample_rate: int) -> float | None:
    """
    Read the time.dat file (int32 sample indices) and compute recording
    duration in seconds.  Returns None if the file is missing.
    """
    time_file = session_dir / "time.dat"
    if not time_file.exists():
        warnings.warn(f"time.dat not found in {session_dir} – duration unknown")
        return None
    n_samples = time_file.stat().st_size // 4   # int32 = 4 bytes each
    return n_samples / sample_rate


def _move_if_exists(src: Path, dst: Path, dry_run: bool = False,
                    copy: bool = False) -> bool:
    if not src.exists():
        return False
    if dry_run:
        action = "COPY" if copy else "MOVE"
        print(f"    [dry] {action}  {src}  →  {dst}")
        return True
    dst.parent.mkdir(parents=True, exist_ok=True)
    if copy:
        # copyfile, not copy2: copy2 also chmod's the destination to match
        # source permissions, which network mounts (e.g. GVFS/FUSE SMB
        # shares) commonly don't support.
        shutil.copyfile(src, dst)
    else:
        shutil.move(str(src), str(dst))
    return True


def rename_copy_intan(
    animal_id: str,
    data_dir: Path | None = None,
    dry_run: bool = False,
    sample_rate: int = cfg.DEFAULT_SAMPLE_RATE,
) -> Tuple[List[str], List[float], str]:
    """
    Main entry point.  Returns (rec_list, durations, merge_name).
    """
    if data_dir is None:
        data_dir = Path.cwd()

    result = _find_session_folders(animal_id, data_dir)
    if not result:
        return [], [], ""

    sessions, merge_name = result
    n_rec = len(sessions)
    rec_list: List[str]   = []
    durations: List[float] = []

    for idx, (start_time, folder_name, folder_path) in enumerate(sessions):
        num     = f"{idx+1:02d}"
        newbase = f"{merge_name}-{num}"          # e.g. KMM43-260311-01
        newbase_path = data_dir / newbase
        rec_list.append(newbase)

        print(f"  Session {num}: {folder_name}  →  {newbase}")

        # ── amplifier.dat → AnimalID-YYMMDD-NN.dat ────────────────────────
        _move_if_exists(folder_path / "amplifier.dat",
                        data_dir / f"{newbase}.dat",
                        dry_run=dry_run)

        # ── amplifier.xml → AnimalID-YYMMDD-NN.xml ────────────────────────
        xml_src = folder_path / "amplifier.xml"
        if not xml_src.exists():
            # fall back to parent directory (lab convention)
            xml_src = data_dir / "amplifier.xml"
        _move_if_exists(xml_src,
                        data_dir / f"{newbase}.xml",
                        dry_run=dry_run)

        # ── amplifier.nrs → AnimalID-YYMMDD-NN.nrs ────────────────────────
        _move_if_exists(folder_path / "amplifier.nrs",
                        data_dir / f"{newbase}.nrs",
                        dry_run=dry_run)

        # ── supply.dat → delete ────────────────────────────────────────────
        supply = folder_path / "supply.dat"
        if supply.exists():
            if dry_run:
                print(f"    [dry] DELETE  {supply}")
            else:
                supply.unlink()

        # ── time.dat → used for duration, then moved ───────────────────────
        dur = _get_duration_from_time_dat(folder_path, sample_rate)
        durations.append(dur if dur is not None else 0.0)
        _move_if_exists(folder_path / "time.dat",
                        newbase_path / f"{newbase}_time.dat",
                        dry_run=dry_run)

        # ── analogin.dat ───────────────────────────────────────────────────
        _move_if_exists(folder_path / "analogin.dat",
                        newbase_path / f"{newbase}_analogin.dat",
                        dry_run=dry_run)

        # ── auxiliary.dat ──────────────────────────────────────────────────
        _move_if_exists(folder_path / "auxiliary.dat",
                        newbase_path / f"{newbase}_auxiliary.dat",
                        dry_run=dry_run)

        # ── digitalin.dat ──────────────────────────────────────────────────
        if cfg.SAVE_DIGITALIN:
            _move_if_exists(folder_path / "digitalin.dat",
                            newbase_path / f"{newbase}_digitalin.dat",
                            dry_run=dry_run)

        # ── info.rhd ───────────────────────────────────────────────────────
        _move_if_exists(folder_path / "info.rhd",
                        newbase_path / f"{newbase}_info.rhd",
                        dry_run=dry_run)

        # ── video file (avi / mpg / mov) ───────────────────────────────────
        video_moved = False
        for ext in cfg.VIDEO_EXTENSIONS:
            candidates = list(folder_path.glob(f"*{ext}"))
            if candidates:
                if len(candidates) > 1:
                    warnings.warn(
                        f"Multiple video files in {folder_path}; using first: "
                        f"{candidates[0].name}")
                _move_if_exists(candidates[0],
                                newbase_path / f"{newbase}.avi",
                                dry_run=dry_run)
                video_moved = True
                break
        if not video_moved:
            pass   # no video is normal

        # ── csv (position / tracking) ──────────────────────────────────────
        csv_files = list(folder_path.glob("*.csv"))
        if csv_files:
            _move_if_exists(csv_files[0],
                            data_dir / f"{newbase}.csv",
                            dry_run=dry_run)
        else:
            warnings.warn(f"No CSV file found in {folder_path}")

        # ── remove original (now-empty) session folder ─────────────────────
        if cfg.ERASE_ORIGINAL_DIRS and not dry_run:
            remaining = list(folder_path.iterdir())
            if remaining:
                print(f"    WARNING: {folder_path} not empty, skipping removal.")
                print(f"    Remaining: {[f.name for f in remaining]}")
            else:
                folder_path.rmdir()

    return rec_list, durations, merge_name
