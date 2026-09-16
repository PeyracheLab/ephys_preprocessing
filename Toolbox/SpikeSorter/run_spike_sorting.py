"""
run_spike_sorting.py
====================
Standalone entry point for SpikeSorter.

Can be called directly after preprocessing or invoked automatically by
IntanProcessing2 (and future OpenEphysProcessing).

USAGE
-----
    python run_spike_sorting.py KMM43-260311

Or with explicit options:

    python run_spike_sorting.py KMM43-260311 \\
        --data-dir "D:/Data/KMM43-260311"   \\
        --probe neuronexus_a1x32            \\
        --output-format neurosuite

Two probes:

    python run_spike_sorting.py KMM43-260311 \\
        --probe neuronexus_a1x32 cambridge_p64

OPTIONS
-------
  --data-dir PATH                     Directory containing .dat/.xml
                                      (default: current working directory)
  --probe NAME_OR_PATH [NAME_OR_PATH] Probe name(s) from Toolbox/Probes/ or
                                      path(s) to probe JSON file(s).
                                      Pass two values for two-probe recordings.
                                      If omitted: looks for probe.json in data_dir,
                                      then falls back to --layout.
  --layout {staggered,linear,columns} Fallback geometry (default: staggered).
                                      Used only when no probe file is found.
  --site-spacing FLOAT                Fallback inter-electrode distance in µm
                                      (default: 20.0)
  --output-format {neurosuite,phy}    Export format (default: neurosuite)
  --export-only                       Skip KiloSort 4; re-export from the
                                      existing kilosort4/ folder
  --dry-run                           Print what would be done without doing it
"""

import argparse
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from sorter import run_sorting
from sorter import config as cfg


def parse_args():
    p = argparse.ArgumentParser(
        description="SpikeSorter – KiloSort 4 runner with Neurosuite / Phy export",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "merge_name",
        help="Base name of the merged recording (e.g. KMM43-260311)"
    )
    p.add_argument(
        "--data-dir", type=Path, default=None,
        help="Directory containing {merge_name}.dat and .xml (default: cwd)"
    )
    p.add_argument(
        "--probe", nargs="+", default=None, metavar="NAME_OR_PATH",
        help="Probe name(s) from probe library or path(s) to JSON file(s). "
             "Pass two values for a two-probe recording."
    )
    p.add_argument(
        "--layout", choices=["staggered", "linear", "columns"],
        default=cfg.DEFAULT_LAYOUT,
        help=f"Fallback geometry layout (default: {cfg.DEFAULT_LAYOUT}). "
             "Used only when no probe file is found."
    )
    p.add_argument(
        "--site-spacing", type=float, default=cfg.DEFAULT_SITE_SPACING,
        metavar="MICRONS",
        help=f"Fallback inter-electrode distance in µm (default: {cfg.DEFAULT_SITE_SPACING})"
    )
    p.add_argument(
        "--output-format", choices=["neurosuite", "phy"],
        default=cfg.DEFAULT_OUTPUT_FORMAT,
        help=f"Export format (default: {cfg.DEFAULT_OUTPUT_FORMAT})"
    )
    p.add_argument(
        "--export-only", action="store_true",
        help="Skip KiloSort 4 and re-export from the existing kilosort4/ folder"
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="Print actions without executing them"
    )
    return p.parse_args()


def main():
    args = parse_args()

    data_dir = (args.data_dir or Path.cwd()).resolve()
    if not data_dir.is_dir():
        sys.exit(f"ERROR: directory does not exist: {data_dir}")

    probe_names = args.probe or []
    if len(probe_names) > 2:
        sys.exit("ERROR: at most two probe files are supported.")

    print(f"\n{'='*60}")
    print(f"  SpikeSorter")
    print(f"  Recording     : {args.merge_name}")
    print(f"  Data dir      : {data_dir}")
    print(f"  Probe(s)      : {probe_names or '(auto-detect)'}")
    print(f"  Output format : {args.output_format}")
    print(f"  Dry run       : {args.dry_run}")
    print(f"{'='*60}\n")

    run_sorting(
        merge_name    = args.merge_name,
        data_dir      = data_dir,
        output_format = args.output_format,
        probe_names   = probe_names,
        layout        = args.layout,
        site_spacing  = args.site_spacing,
        export_only   = args.export_only,
        dry_run       = args.dry_run,
    )


if __name__ == "__main__":
    main()
