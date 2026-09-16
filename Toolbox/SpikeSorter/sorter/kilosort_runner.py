"""
kilosort_runner.py
==================
Runs KiloSort 4 on a merged .dat file and returns the path to the results folder.

Input expected in work_dir:
  - {merge_name}.dat   : merged broadband recording (int16, channels interleaved)
  - {merge_name}.xml   : Neuroscope parameter file

Output:
  - work_dir/kilosort4/   : KS4 results directory
"""

import sys
import subprocess
from pathlib import Path
from typing import Optional

import numpy as np

from . import config as cfg
from .xml_tools import load_xml, XmlParams


def run_kilosort4(
    merge_name: str,
    work_dir:   Path,
    probe_dict: dict,
    dry_run:    bool = False,
) -> Path:
    """
    Run KiloSort 4 on {work_dir}/{merge_name}.dat.

    Parameters
    ----------
    merge_name : base name of the merged recording
    work_dir   : directory containing the .dat file
    probe_dict : KS4 probe dict (chanMap, xc, yc, kcoords, connected, n_chan)
                 built by probe_utils.build_probe_dict()
    dry_run    : print what would be done without executing

    Returns
    -------
    Path to the kilosort4/ results directory.
    """
    work_dir    = Path(work_dir)
    dat_path    = work_dir / f"{merge_name}.dat"
    xml_path    = work_dir / f"{merge_name}.xml"
    results_dir = work_dir / "kilosort4"

    if not dat_path.exists() and not dry_run:
        raise FileNotFoundError(f"Merged .dat not found: {dat_path}")

    params = None
    if xml_path.exists():
        params = load_xml(xml_path)

    n_channels  = params.n_channels  if params else probe_dict["n_chan"]
    sample_rate = params.sample_rate if params else cfg.DEFAULT_SAMPLE_RATE

    if dry_run:
        print(f"  [dry] Would run KiloSort 4")
        print(f"        data   : {dat_path}")
        print(f"        output : {results_dir}")
        print(f"        n_chan : {n_channels}   fs: {sample_rate} Hz")
        print(f"        active : {sum(probe_dict['connected'])} / {n_channels} channels")
        return results_dir

    try:
        import kilosort  # noqa: F401
        _ks4_api(merge_name, work_dir, n_channels, sample_rate, probe_dict, results_dir)
    except ImportError:
        print("  kilosort package not importable – trying subprocess fallback...")
        _ks4_subprocess(merge_name, work_dir, n_channels, sample_rate, probe_dict, results_dir)

    return results_dir


# ── KS4 via Python API ─────────────────────────────────────────────────────────

def _ks4_api(
    merge_name:  str,
    work_dir:    Path,
    n_channels:  int,
    sample_rate: int,
    probe_dict:  dict,
    results_dir: Path,
) -> None:
    from kilosort import run_kilosort

    settings = {
        "data_dir":    str(work_dir),
        "results_dir": str(results_dir),
        "filename":    str(work_dir / f"{merge_name}.dat"),
        "n_chan_bin":  n_channels,
        "fs":          sample_rate,
        "batch_size":  cfg.KS4_BATCH_SIZE,
        "nblocks":     cfg.KS4_NBLOCKS,
    }

    # KS4 requires numpy arrays (not lists) in the probe dict
    probe = {
        "chanMap":   np.array(probe_dict["chanMap"],   dtype=np.int32),
        "xc":        np.array(probe_dict["xc"],        dtype=np.float32),
        "yc":        np.array(probe_dict["yc"],        dtype=np.float32),
        "kcoords":   np.array(probe_dict["kcoords"],   dtype=np.float32),
        "connected": np.array(probe_dict["connected"], dtype=bool),
        "n_chan":     probe_dict["n_chan"],
    }

    print(f"  Running KiloSort 4 …  output → {results_dir}")
    print(f"  Active channels: {probe['connected'].sum()} / {n_channels}")
    run_kilosort(settings=settings, probe=probe)
    print("  KiloSort 4 complete.")


# ── KS4 via subprocess fallback ────────────────────────────────────────────────

def _ks4_subprocess(
    merge_name:  str,
    work_dir:    Path,
    n_channels:  int,
    sample_rate: int,
    probe_dict:  dict,
    results_dir: Path,
) -> None:
    import json as _json
    results_dir.mkdir(parents=True, exist_ok=True)
    probe_json = work_dir / "_probe_tmp.json"
    probe_json.write_text(_json.dumps(probe_dict))

    runner = work_dir / "_ks4_runner.py"
    runner.write_text(
        f"import json\n"
        f"from kilosort import run_kilosort\n"
        f"probe = json.loads(open({str(probe_json)!r}).read())\n"
        f"run_kilosort(settings={{\n"
        f"    'data_dir':    {str(work_dir)!r},\n"
        f"    'results_dir': {str(results_dir)!r},\n"
        f"    'filename':    {merge_name + '.dat'!r},\n"
        f"    'n_chan_bin':  {n_channels},\n"
        f"    'fs':          {sample_rate},\n"
        f"    'data_dtype':  'int16',\n"
        f"}}, probe=probe)\n"
        f"print('KiloSort 4 done.')\n"
    )
    print(f"  Subprocess: {sys.executable} {runner}")
    subprocess.run([sys.executable, str(runner)], cwd=str(work_dir), check=True)
    runner.unlink(missing_ok=True)
    probe_json.unlink(missing_ok=True)
