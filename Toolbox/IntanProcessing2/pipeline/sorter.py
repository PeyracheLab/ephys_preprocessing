"""
sorter.py
=========
Launches the selected spike sorter on the merged data.

Supported sorters
-----------------
kilosort4   : KiloSort 4 (Python).  Must be installed in the active conda env.
              pip install kilosort   OR   conda install -c conda-forge kilosort
              https://github.com/MouseLand/Kilosort

kilosort2_5 : KiloSort 2.5 (MATLAB).  Requires MATLAB + KS2.5 on the MATLAB path.
              Calls MATLAB as a subprocess, running KiloSort25Wrapper.m.

Both sorters are called from *within* the final output folder (merge_name/),
which already contains merge_name.dat and merge_name.xml.
"""

import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

from . import config as cfg
from .xml_tools import load_xml, XmlParams


# ─────────────────────────────────────────────────────────────────────────────
#  Public entry point
# ─────────────────────────────────────────────────────────────────────────────

def launch_sorter(
    merge_name: str,
    sorter: str,
    work_dir: Optional[Path] = None,
    dry_run: bool = False,
) -> None:
    """
    Launch the spike sorter.

    Parameters
    ----------
    merge_name : base name of the merged recording (e.g. 'KMM43-260311')
    sorter     : 'kilosort4' or 'kilosort2_5'
    work_dir   : directory to run from (default: cwd, which should be merge_name/)
    dry_run    : print the command without executing
    """
    if work_dir is None:
        work_dir = Path.cwd()

    xml_path = work_dir / f"{merge_name}.xml"
    dat_path = work_dir / f"{merge_name}.dat"

    if not dat_path.exists() and not dry_run:
        raise FileNotFoundError(f"Merged .dat not found: {dat_path}")

    # Load recording parameters from XML
    params: Optional[XmlParams] = None
    if xml_path.exists():
        params = load_xml(xml_path)
    else:
        print(f"  WARNING: {xml_path} not found – using config defaults")

    n_channels   = params.n_channels   if params else 0
    sample_rate  = params.sample_rate  if params else cfg.DEFAULT_SAMPLE_RATE

    if sorter == "kilosort4":
        _run_kilosort4(merge_name, work_dir, n_channels, sample_rate, dry_run)
    elif sorter == "kilosort2_5":
        _run_kilosort25(merge_name, work_dir, dry_run)
    else:
        raise ValueError(f"Unknown sorter: {sorter!r}")


# ─────────────────────────────────────────────────────────────────────────────
#  KiloSort 4
# ─────────────────────────────────────────────────────────────────────────────

def _run_kilosort4(
    merge_name: str,
    work_dir: Path,
    n_channels: int,
    sample_rate: int,
    dry_run: bool,
) -> None:
    """
    Run KiloSort 4 via its Python API.

    KS4 is called programmatically so that:
      - The probe / channel map from the XML is respected
      - No manual GUI interaction is needed
      - Results land in work_dir/kilosort4/

    If kilosort is not importable, we fall back to subprocess call.
    """
    results_dir = work_dir / "kilosort4"

    if dry_run:
        print(f"    [dry] Would run KiloSort 4")
        print(f"          data   : {work_dir / f'{merge_name}.dat'}")
        print(f"          output : {results_dir}")
        print(f"          n_ch   : {n_channels}   fs: {sample_rate} Hz")
        return

    try:
        import kilosort
        _ks4_api(merge_name, work_dir, n_channels, sample_rate, results_dir)
    except ImportError:
        print("  kilosort package not importable – trying subprocess...")
        _ks4_subprocess(merge_name, work_dir, n_channels, sample_rate, results_dir)


def _ks4_api(
    merge_name: str,
    work_dir: Path,
    n_channels: int,
    sample_rate: int,
    results_dir: Path,
) -> None:
    """Use the kilosort Python API directly."""
    from kilosort import run_kilosort
    from kilosort.utils import PROBE_DIR

    # Build a minimal probe dict from the XML spike groups
    xml_path = work_dir / f"{merge_name}.xml"
    params_xml = load_xml(xml_path) if xml_path.exists() else None

    # KS4 settings – these are safe defaults; power users can edit config.py
    settings = {
        "data_dir":       str(work_dir),
        "results_dir":    str(results_dir),
        "filename":       f"{merge_name}.dat",
        "n_chan_bin":     n_channels,
        "fs":             sample_rate,
        "dtype":          "int16",
        "batch_size":     60_000,
        "nblocks":        1,         # rigid drift correction; set >1 for non-rigid
    }

    print(f"  Running KiloSort 4 …")
    print(f"    output → {results_dir}")

    # Build probe from XML anatomical groups if available
    probe = _build_probe_from_xml(params_xml, n_channels)

    run_kilosort(settings=settings, probe=probe)
    print("  KiloSort 4 complete.")


def _ks4_subprocess(
    merge_name: str,
    work_dir: Path,
    n_channels: int,
    sample_rate: int,
    results_dir: Path,
) -> None:
    """
    Fall back: write a small Python runner script and call it as a subprocess.
    Useful when the pipeline is invoked from a different Python env.
    """
    runner = work_dir / "_ks4_runner.py"
    results_dir.mkdir(parents=True, exist_ok=True)

    runner.write_text(f"""
import sys
from kilosort import run_kilosort

settings = {{
    "data_dir":    {str(work_dir)!r},
    "results_dir": {str(results_dir)!r},
    "filename":    {merge_name + '.dat'!r},
    "n_chan_bin":  {n_channels},
    "fs":          {sample_rate},
    "dtype":       "int16",
}}
run_kilosort(settings=settings)
print("KiloSort 4 done.")
""")

    cmd = [sys.executable, str(runner)]
    print(f"  Subprocess: {' '.join(cmd)}")
    subprocess.run(cmd, cwd=str(work_dir), check=True)
    runner.unlink(missing_ok=True)


def _build_probe_from_xml(params: Optional[XmlParams], n_channels: int) -> dict:
    """
    Build a minimal KS4 probe dictionary from the XML anatomical groups.
    If no groups are available, creates a linear probe with all channels.

    KS4 probe format:
        {'chanMap': [...], 'xc': [...], 'yc': [...], 'kcoords': [...], 'n_chan': N}
    """
    if params and params.anat_grps:
        all_channels = []
        kcoords = []
        for grp_idx, grp in enumerate(params.anat_grps):
            for ch in grp.channels:
                if not grp.skip or grp.skip[grp.channels.index(ch)] == 0:
                    all_channels.append(ch)
                    kcoords.append(grp_idx + 1)
    else:
        all_channels = list(range(n_channels))
        kcoords      = [1] * n_channels

    # Assume a simple linear shank layout (25 µm pitch) – user can override
    yc = [i * 25 for i in range(len(all_channels))]
    xc = [0]     * len(all_channels)

    return {
        "chanMap":  all_channels,
        "xc":       xc,
        "yc":       yc,
        "kcoords":  kcoords,
        "n_chan":   n_channels,
    }


# ─────────────────────────────────────────────────────────────────────────────
#  KiloSort 2.5  (MATLAB)
# ─────────────────────────────────────────────────────────────────────────────

def _run_kilosort25(
    merge_name: str,
    work_dir: Path,
    dry_run: bool,
) -> None:
    """
    Run KiloSort 2.5 by calling MATLAB as a subprocess.

    Requires:
      - MATLAB executable on PATH  (or set cfg.MATLAB_EXECUTABLE)
      - KiloSort25Wrapper.m on the MATLAB path  (or set cfg.KILOSORT25_SCRIPT)
    """
    matlab_exe = cfg.MATLAB_EXECUTABLE or "matlab"

    # Build MATLAB command string
    ks_call = "KiloSort25Wrapper"
    matlab_cmd = (
        f"cd('{work_dir}'); "
        f"try, {ks_call}; catch e, "
        f"disp(e.message), exit(1), end; exit(0);"
    )

    cmd = [
        matlab_exe,
        "-batch", matlab_cmd,
    ]

    if dry_run:
        print(f"    [dry] Would run KiloSort 2.5 via MATLAB:")
        print(f"          {' '.join(cmd)}")
        return

    print(f"  Launching MATLAB + KiloSort 2.5 …")
    result = subprocess.run(cmd, cwd=str(work_dir))
    if result.returncode != 0:
        raise RuntimeError(
            f"KiloSort 2.5 / MATLAB exited with code {result.returncode}")
    print("  KiloSort 2.5 complete.")
