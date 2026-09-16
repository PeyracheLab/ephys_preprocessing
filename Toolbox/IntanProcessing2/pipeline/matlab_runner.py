"""
matlab_runner.py
================
Runs MATLAB scripts (Process_LFPfromDat, SleepScoreMaster) as a subprocess
using MATLAB's -batch flag (non-interactive, auto-exits, non-zero on error).

Process_LFPfromDat lives in Toolbox/buzcode/peyrache_edits (a batch-safe fork of
buzcode's bz_LFPfromDat.m — writes .eeg instead of .lfp, and has no interactive
prompts or `keyboard` breakpoints, both of which would hang an unattended
`matlab -batch` run). SleepScoreMaster lives in Toolbox/buzcode proper.
"""

import glob as _glob
import subprocess
import sys
from pathlib import Path
from typing import Optional

from . import config as cfg
from .xml_tools import load_xml

_SCRIPT_DIR  = Path(__file__).resolve().parent          # .../IntanProcessing2/pipeline
_TOOLBOX_DIR = _SCRIPT_DIR.parent.parent                 # .../Toolbox


def _default_toolbox_paths() -> list:
    # peyrache_edits lives inside buzcode/, so genpath(buzcode) already covers it.
    return [
        _TOOLBOX_DIR / "buzcode",
    ]


def find_matlab() -> Path:
    """
    Locate the MATLAB executable.

    Search order:
      1. MATLAB_EXECUTABLE in config.py (if set)
      2. 'matlab' on the system PATH
      3. Common Windows install locations (C:/Program Files/MATLAB/R*/bin/matlab.exe)

    Raises RuntimeError with a helpful message if not found.
    """
    if cfg.MATLAB_EXECUTABLE:
        exe = Path(cfg.MATLAB_EXECUTABLE)
        if exe.exists():
            return exe
        raise RuntimeError(
            f"MATLAB_EXECUTABLE in config.py points to a non-existent path:\n"
            f"  {exe}\n"
            "Update MATLAB_EXECUTABLE in IntanProcessing2/pipeline/config.py."
        )

    # Check PATH
    try:
        result = subprocess.run(
            ["where", "matlab"] if sys.platform == "win32" else ["which", "matlab"],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            return Path(result.stdout.strip().splitlines()[0])
    except FileNotFoundError:
        pass

    # Scan common Windows install paths
    if sys.platform == "win32":
        patterns = [
            r"C:\Program Files\MATLAB\R*\bin\matlab.exe",
            r"C:\Program Files (x86)\MATLAB\R*\bin\matlab.exe",
        ]
        candidates = []
        for pat in patterns:
            candidates.extend(_glob.glob(pat))
        if candidates:
            # Pick the most recent release (lexicographic sort on Rxxxx is correct)
            return Path(sorted(candidates)[-1])

    raise RuntimeError(
        "MATLAB executable not found.\n"
        "Set MATLAB_EXECUTABLE in IntanProcessing2/pipeline/config.py, e.g.:\n"
        r'  MATLAB_EXECUTABLE = r"C:\Program Files\MATLAB\R2024b\bin\matlab.exe"'
    )


def _skip_channels_from_xml(base_path: Path) -> list:
    """
    Return a list of 0-based channel indices marked skip=1 in the XML's
    anatomical channel groups.  Returns an empty list if the XML is missing
    or no channels are flagged.
    """
    xml_path = base_path / f"{base_path.name}.xml"
    if not xml_path.exists():
        return []
    params = load_xml(xml_path)
    skipped = [
        ch
        for grp in params.anat_grps
        for ch, sk in zip(grp.channels, grp.skip)
        if sk == 1
    ]
    return skipped


def run_lfp_sleep(
    base_path:        Path,
    out_fs:           int  = None,
    lo_pass:          int  = None,
    skip_lfp:         bool = False,
    skip_sleep_score: bool = True,
    dry_run:          bool = False,
) -> None:
    """
    Run Process_LFPfromDat and/or SleepScoreMaster on a recording folder via MATLAB -batch.

    Parameters
    ----------
    base_path        : recording folder containing <name>.dat and <name>.xml
    out_fs           : LFP output sample rate in Hz (default: cfg.LFP_SAMPLE_RATE)
    lo_pass          : lowpass cutoff in Hz (default: cfg.LFP_LO_PASS)
    skip_lfp         : skip Process_LFPfromDat (re-use existing .eeg)
    skip_sleep_score : skip SleepScoreMaster (default True — sleep scoring is opt-in)
    dry_run          : print command without executing
    """
    if skip_lfp and skip_sleep_score:
        return

    out_fs  = out_fs  if out_fs  is not None else cfg.LFP_SAMPLE_RATE
    lo_pass = lo_pass if lo_pass is not None else cfg.LFP_LO_PASS

    toolbox_paths = cfg.MATLAB_TOOLBOX_PATHS or _default_toolbox_paths()

    # Forward slashes — MATLAB accepts them on Windows and avoids backslash escaping
    bp = str(base_path.resolve()).replace("\\", "/")

    # Build addpath block
    addpath_cmds = "; ".join(
        f"addpath(genpath('{Path(p).as_posix()}'))"
        for p in toolbox_paths
    )

    # Build function calls
    calls = []
    if not skip_lfp:
        calls.append(
            f"Process_LFPfromDat('{bp}', 'outFs', {out_fs}, 'lopass', {lo_pass})"
        )
    if not skip_sleep_score:
        reject_chans = _skip_channels_from_xml(base_path)
        if reject_chans:
            chan_vec = " ".join(str(c) for c in reject_chans)
            reject_arg = f", 'rejectChannels', [{chan_vec}]"
            print(f"  Channels skipped (from XML): {reject_chans}")
        else:
            reject_arg = ""
            print("  Channels skipped (from XML): none")
        calls.append(
            f"SleepScoreMaster('{bp}', 'noPrompts', true{reject_arg})"
        )

    batch_expr = "; ".join([addpath_cmds] + calls)

    matlab_exe = find_matlab()
    cmd = [str(matlab_exe), "-batch", batch_expr]

    print(f"  MATLAB : {matlab_exe}")
    print(f"  Command: matlab -batch \"{addpath_cmds}; {'; '.join(calls)}\"")

    if dry_run:
        return

    subprocess.run(cmd, check=True)
