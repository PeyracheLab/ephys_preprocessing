"""
master_preprocessing.py
=======================
Main entry point for the Intan pre-processing pipeline.

USAGE
-----
Run from the folder that *contains* the Intan session folders:

    python master_preprocessing.py KMM43

or, if your current working directory IS the data folder:

    python master_preprocessing.py

The script will infer the AnimalID from the session folder names if not
supplied (all folders must share the same AnimalID prefix).

OPTIONS
-------
  --skip-sorting                          Pre-process only, do not launch sorter
  --no-concatenate                        Do not merge each day's recording bouts into one
                                          session; keep each raw bout as its own folder
                                          (AnimalID-YYMMDD-NN) and spike-sort it separately.
  --output-format {neurosuite,phy}        Spike sorting export format (default: neurosuite)
  --data-dir PATH                         Data directory (default: current working dir)
  --dry-run                               Print what would be done without doing it
  --no-analogin                           Do not copy analogin files into the merge folder
  --no-digitalin                          Do not copy digitalin files into the merge folder
  --no-auxiliary                          Do not concatenate auxiliary files into the merge folder
  --work-dir PATH                         Fast scratch drive for processing (e.g. NVMe SSD).
                                          Session data is copied there, all steps run on fast
                                          storage, then output is copied back. Can also be set
                                          permanently via WORK_DIR in pipeline/config.py.
  --keep-work-dir                         Do not delete the scratch copy after a successful run
  --skip-lfp                              Skip LFP downsampling (Process_LFPfromDat -> .eeg).
                                          Runs by default; use this to disable it.
  --sleep-score                           Run automated sleep scoring (SleepScoreMaster) after
                                          LFP downsampling. Off by default — opt in with this flag.
  --make-nwb                               Build an .nwb file (via nwb-builder) after the pipeline
                                          finishes. Off by default. Since this runs before any
                                          manual cluster curation, the file is named
                                          <merge_name>_dirtyClusters.nwb. If --sleep-score was
                                          also used, sws/rem/wake epochs are included as
                                          pynapple-readable IntervalSets.

PIPELINE STEPS
--------------
  1. Discover session folders  (SessionID_YYMMDD_HHMMSS)
  2. Rename & reorganise files into AnimalID-YYMMDD-NN intermediate folders
  3. Build Epoch_TS.csv from time.dat durations
  4. Merge all per-session .dat files into AnimalID-YYMMDD.dat
  5. Copy / merge auxiliary files (analogin, digitalin, auxiliary, video, csv)
  6. Copy XML parameter file, update <spikeDetection> nSamples etc.
  7. Run KiloSort 4 via SpikeSorter, export to Neurosuite or Phy
  8. Process_LFPfromDat  →  AnimalID-YYMMDD.eeg                      (default on, --skip-lfp to disable)
  9. SleepScoreMaster    →  AnimalID-YYMMDD.SleepState.states.mat    (opt-in via --sleep-score)
 10. Build .nwb via nwb-builder → AnimalID-YYMMDD_dirtyClusters.nwb  (opt-in via --make-nwb)

Author: ported from MasterPreProcessing_Intan25.m  (A. Peyrache 2017)
Python port: auto-generated 2025
"""

import argparse
import sys
import os
import re
import shutil
from pathlib import Path

# Ensure the folder containing this script (the toolbox) is on sys.path,
# regardless of which directory the user runs it from.
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from pipeline.rename_copy   import rename_copy_intan
from pipeline.concatenate   import concatenate_dat_files
from pipeline.xml_tools     import load_xml, update_xml_spk_grps, generate_xml
from pipeline.intan_info    import read_sample_rate
from pipeline.epoch_ts      import build_epoch_ts
from pipeline.file_utils    import move_ancillary_files
from pipeline.per_session   import finalize_single_session
from pipeline.matlab_runner import run_lfp_sleep
from pipeline import config as cfg


def _resolve_kilosort_python() -> str:
    """
    Resolve the python(.exe) that has KiloSort 4 / PyTorch installed.

    Precedence:
      1. KILOSORT_PYTHON in config.py, if explicitly set.
      2. PP_ENV_NAME's interpreter at <repo root>/<PP_ENV_NAME>, i.e. the env
         created by `uv venv PP_ENV_NAME` run from the repo root per the setup
         instructions (Scripts/python.exe on Windows, bin/python on Linux/Mac).
      3. The interpreter currently running this script, as a last resort.
    """
    if getattr(cfg, "KILOSORT_PYTHON", None):
        return cfg.KILOSORT_PYTHON

    repo_root = _SCRIPT_DIR.parent.parent   # Toolbox/IntanProcessing2 -> Toolbox -> repo root
    env_name  = getattr(cfg, "PP_ENV_NAME", "pp_env")
    env_dir   = repo_root / env_name
    exe = (env_dir / "Scripts" / "python.exe") if sys.platform == "win32" \
        else (env_dir / "bin" / "python")

    if exe.exists():
        return str(exe)

    return sys.executable


def _build_nwb(out_dir: Path, merge_name: str, dry_run: bool) -> None:
    """
    Build an .nwb file for the finished session via nwb-builder (shared pp_env
    install — see requirements.txt). Named <merge_name>_dirtyClusters.nwb: this
    runs right after automated KiloSort 4 sorting, before any manual cluster
    curation, so the clusters inside are not yet cleaned.

    If SleepScoreMaster already ran on this session (out_dir/{merge_name}.
    SleepState.states.mat exists), nwb-builder picks it up automatically and
    adds sws/rem/wake epochs as separate TimeIntervals tables, each readable
    back as its own pynapple IntervalSet.
    """
    from nwb_builder.build_nwb import BuildConfig, build

    output_path = out_dir / f"{merge_name}_dirtyClusters.nwb"
    build(BuildConfig(
        session_dir = str(out_dir),
        output_path = str(output_path),
        force       = True,
        dry_run     = dry_run,
    ))


def _run_spike_sorter(
    merge_name:    str,
    data_dir:      Path,
    output_format: str,
    probe_names:   list,
    layout:        str,
    site_spacing:  float,
    dry_run:       bool,
) -> None:
    """
    Launch SpikeSorter in the pp_env environment via subprocess.
    This keeps the heavy KS4 / PyTorch dependencies out of the intan_proc env.
    """
    import subprocess

    print("  NOTE: probe-based geometry assumes each <anatomicalDescription> group "
          "in the XML is exactly one probe shank (same order, same channel count "
          "as the probe file's n_channels_per_shank). If your XML groups channels "
          "some other way (e.g. one group spanning multiple shanks), the geometry "
          "handed to KiloSort will be wrong.")

    spike_sorter_path = cfg.SPIKE_SORTER_PATH
    if spike_sorter_path is None:
        spike_sorter_path = _SCRIPT_DIR.parent / "SpikeSorter"
    script = Path(spike_sorter_path) / "run_spike_sorting.py"

    if not script.exists():
        raise FileNotFoundError(
            f"SpikeSorter script not found at: {script}\n"
            "Set SPIKE_SORTER_PATH in pipeline/config.py to the correct location."
        )

    python_exe = _resolve_kilosort_python()

    cmd = [
        str(python_exe), str(script),
        merge_name,
        "--data-dir",      str(data_dir),
        "--output-format", output_format,
        "--layout",        layout,
        "--site-spacing",  str(site_spacing),
    ]
    if probe_names:
        cmd += ["--probe"] + probe_names
    elif cfg.DEFAULT_PROBE:
        cmd += ["--probe", cfg.DEFAULT_PROBE]
    if dry_run:
        cmd.append("--dry-run")

    print(f"  Command: {' '.join(cmd)}")
    subprocess.run(cmd, check=True)


def _backup_original_clu_files(out_dir: Path, merge_name: str, dry_run: bool) -> None:
    """
    Copy the freshly-sorted .clu.N files into out_dir/OriginalClus/.

    Klusters occasionally crashes and corrupts a .clu file while a student is
    manually curating clusters. Keeping an untouched copy of the original,
    just-sorted .clu files means they can restore from here and re-curate
    without having to re-run spike sorting from scratch.
    """
    clu_files = sorted(out_dir.glob(f"{merge_name}.clu.*"))
    if not clu_files:
        return

    backup_dir = out_dir / "OriginalClus"
    if dry_run:
        print(f"    [dry] Would back up {len(clu_files)} .clu file(s) → {backup_dir}")
        return

    backup_dir.mkdir(exist_ok=True)
    for f in clu_files:
        shutil.copy2(f, backup_dir / f.name)
    print(f"  Backed up {len(clu_files)} original .clu file(s) → {backup_dir}")


def parse_args():
    p = argparse.ArgumentParser(
        description="Intan pre-processing pipeline (Python port of MasterPreProcessing_Intan25)")
    p.add_argument("animal_id", nargs="?", default=None,
                   help="AnimalID prefix (e.g. KMM43). Inferred automatically if omitted.")
    p.add_argument("--skip-sorting", action="store_true",
                   help="Pre-process only; do not launch spike sorter")
    p.add_argument("--no-concatenate", action="store_true",
                   help="Do not merge each day's recording bouts into one session. "
                        "Keep each raw bout as its own AnimalID-YYMMDD-NN folder and "
                        "spike-sort it separately.")
    p.add_argument("--output-format", choices=["neurosuite", "phy"],
                   default=cfg.DEFAULT_OUTPUT_FORMAT,
                   help=f"Spike sorting export format (default: {cfg.DEFAULT_OUTPUT_FORMAT})")
    p.add_argument("--probe", nargs="+", default=None, metavar="NAME_OR_PATH",
                   help="Probe name(s) from Toolbox/Probes/ or path(s) to probe JSON. "
                        "Pass two values for a two-probe recording.")
    p.add_argument("--layout", choices=["staggered", "linear", "columns"],
                   default="staggered",
                   help="Fallback probe geometry if no probe file is found (default: staggered)")
    p.add_argument("--site-spacing", type=float, default=20.0, metavar="MICRONS",
                   help="Fallback inter-electrode distance in µm (default: 20.0)")
    p.add_argument("--data-dir", type=Path, default=None,
                   help="Directory containing session folders (default: cwd)")
    p.add_argument("--dry-run", action="store_true",
                   help="Print actions without executing them")
    p.add_argument("--sample-rate", type=int, default=0, metavar="HZ",
                   help="Recording sample rate in Hz.  Auto-detected from info.rhd "
                        f"when omitted; falls back to {cfg.DEFAULT_SAMPLE_RATE} Hz.")
    p.add_argument("--no-analogin", action="store_true",
                   help="Do not copy analogin files into the merge folder")
    p.add_argument("--no-digitalin", action="store_true",
                   help="Do not copy digitalin files into the merge folder")
    p.add_argument("--no-auxiliary", action="store_true",
                   help="Do not concatenate auxiliary files into the merge folder")
    p.add_argument("--work-dir", type=Path, default=None, metavar="PATH",
                   help="Fast scratch directory (e.g. a local NVMe SSD) to run "
                        "processing in. Session data is copied there first, all "
                        "steps run on fast storage, then the output folder is "
                        "copied back. Overrides WORK_DIR in config.py.")
    p.add_argument("--keep-work-dir", action="store_true",
                   help="Do not delete the scratch copy after a successful run "
                        "(useful for debugging or if you want the output in place)")
    p.add_argument("--skip-lfp", action="store_true",
                   help="Skip LFP downsampling (Process_LFPfromDat -> .eeg). "
                        "Runs by default; use this flag to disable it.")
    p.add_argument("--sleep-score", action="store_true",
                   help="Run automated sleep scoring (SleepScoreMaster) after LFP "
                        "downsampling. Off by default — opt in with this flag.")
    p.add_argument("--make-nwb", action="store_true",
                   help="Build an .nwb file (via nwb-builder) after the pipeline "
                        "finishes. Off by default. Named <merge_name>_dirtyClusters.nwb "
                        "since clusters haven't been manually curated yet.")
    return p.parse_args()


def infer_animal_id(data_dir: Path) -> str:
    """
    If AnimalID is not provided, look at folder names of the form
    AnimalID_YYMMDD_HHMMSS and extract the common prefix before the first '_'.
    """
    candidates = set()
    for d in data_dir.iterdir():
        if not d.is_dir():
            continue
        parts = d.name.split("_")
        # Expect at least 3 parts: AnimalID, YYMMDD, HHMMSS
        if len(parts) >= 3 and parts[-1].isdigit() and parts[-2].isdigit():
            # Everything before the last two underscore-parts is the AnimalID
            animal_id = "_".join(parts[:-2])
            candidates.add(animal_id)
    if len(candidates) == 0:
        raise RuntimeError(
            "No session folders found. Expected folders named AnimalID_YYMMDD_HHMMSS.")
    if len(candidates) > 1:
        raise RuntimeError(
            f"Multiple AnimalIDs found: {candidates}. "
            "Please specify the AnimalID explicitly as a positional argument.")
    return candidates.pop()


def _find_probe_json(probe_names: list, data_dir: Path) -> "Path | None":
    """
    Return the path to a usable probe JSON file, or None.

    Search order:
      1. probe.json in data_dir
      2. Each entry in probe_names: direct path if it ends in .json and exists,
         otherwise look in Toolbox/Probes/<name>.json
    """
    auto = data_dir / "probe.json"
    if auto.exists():
        return auto
    probe_lib = _SCRIPT_DIR.parent / "Probes"
    for name in probe_names:
        p = Path(name)
        if p.suffix.lower() == ".json" and p.exists():
            return p
        for candidate in [probe_lib / name, probe_lib / f"{name}.json"]:
            if candidate.exists():
                return candidate
    return None


def _groups_from_probe(probe: dict) -> tuple:
    """
    Return (n_total_channels, groups) from a probe dict.

    n_channels_per_shank may be a single int (uniform shanks) or a list with
    one entry per shank (e.g. Buzsaki64sp, where one shank carries extra
    deep channels beyond the usual tip cluster). Channels are assumed to be
    laid out shank-by-shank in raw/wired order, matching how probe_utils.py
    (SpikeSorter) indexes xc/yc/kcoords by physical channel number.
    """
    ncpp = probe["n_channels_per_shank"]
    n_sh = probe["n_shanks"]
    counts = [int(ncpp)] * n_sh if isinstance(ncpp, int) else [int(c) for c in ncpp]

    if len(counts) != n_sh:
        raise ValueError(
            f"Probe '{probe.get('name', 'unnamed')}': n_channels_per_shank has "
            f"{len(counts)} entries but n_shanks={n_sh}."
        )

    groups = []
    start = 0
    for n_ch in counts:
        groups.append(list(range(start, start + n_ch)))
        start += n_ch
    return start, groups


def _resolve_session_xml(
    rec: str,
    out_dir: Path,
    data_dir: Path,
    args,
    sample_rate: int,
) -> Path:
    """
    Ensure out_dir/{rec}.xml exists, falling back to amplifier.xml in
    data_dir (or its parent) or a probe-generated XML, same precedence as
    the merged-mode XML resolution in main(). Used by --no-concatenate.
    """
    import json as _json

    dst_xml = out_dir / f"{rec}.xml"
    if dst_xml.exists() or args.dry_run:
        return dst_xml

    for xml_candidate in [data_dir / "amplifier.xml", data_dir.parent / "amplifier.xml"]:
        if xml_candidate.exists():
            shutil.copy2(xml_candidate, dst_xml)
            print(f"      XML copied from {xml_candidate}: {dst_xml.name}")
            return dst_xml

    if not args.skip_sorting:
        probe_path = _find_probe_json(args.probe or [], data_dir)
        if probe_path is not None:
            with open(probe_path) as _f:
                probe = _json.load(_f)
            n_total, groups = _groups_from_probe(probe)
            generate_xml(dst_xml, n_channels=n_total, sample_rate=sample_rate, groups=groups)
            print(f"      XML generated from probe file '{probe_path.name}' "
                  f"({n_total} ch, {len(groups)} shank(s)) for {rec}.")
        else:
            sys.exit(
                f"\nERROR: No XML parameter file and no probe file found for session {rec}.\n"
                "Spike sorting requires one of the following:\n"
                "  • An amplifier.xml in one of the session folders, in\n"
                f"    {data_dir}, or in {data_dir.parent}\n"
                f"  • A probe.json in {data_dir}\n"
                "  • A --probe <name_or_path> argument pointing to a probe JSON\n"
                "Use --skip-sorting to pre-process without sorting."
            )
    return dst_xml


def _run_per_session(args, rec_list, durations, data_dir, sample_rate) -> None:
    """
    --no-concatenate path: finalize and (optionally) spike-sort each raw
    recording bout independently instead of merging them into one session.
    """
    print(f"\n[2/3] Finalizing {len(rec_list)} session folder(s) (--no-concatenate)...")
    session_dirs = []
    for rec, dur in zip(rec_list, durations):
        out_dir = finalize_single_session(
            rec, dur, data_dir,
            dry_run=args.dry_run,
            keep_analogin=not args.no_analogin,
            keep_digitalin=not args.no_digitalin,
            keep_auxiliary=not args.no_auxiliary,
        )
        session_dirs.append(out_dir)
        print(f"      {rec}  ->  {out_dir}")

        dst_xml = _resolve_session_xml(rec, out_dir, data_dir, args, sample_rate)
        if dst_xml.exists() and not args.dry_run:
            update_xml_spk_grps(dst_xml,
                                n_samples=cfg.SPIKE_N_SAMPLES,
                                peak_sample_index=cfg.SPIKE_PEAK_SAMPLE,
                                n_features=cfg.SPIKE_N_FEATURES)

    if args.skip_sorting:
        print("\n[3/3] Spike sorting skipped (--skip-sorting flag).")
        return

    print(f"\n[3/3] Running SpikeSorter separately on {len(rec_list)} session(s) "
          f"(KiloSort 4 → {args.output_format})...")
    for rec, out_dir in zip(rec_list, session_dirs):
        print(f"\n  --- {rec} ---")
        _run_spike_sorter(
            merge_name    = rec,
            data_dir      = out_dir,
            output_format = args.output_format,
            probe_names   = args.probe or [],
            layout        = args.layout,
            site_spacing  = args.site_spacing,
            dry_run       = args.dry_run,
        )


def _copy_back_and_finish(args, scratch_dir, original_data_dir, output_names, data_dir) -> None:
    """
    Shared tail for --no-concatenate: copy each session's output folder back
    from the scratch drive (if one was used) and print a summary.

    No intermediate-file cleanup or rename-prompt here: finalize_single_session
    already leaves each session folder as its own final output, in place, so
    there is nothing left to clean up or rename.
    """
    if scratch_dir and not args.dry_run:
        for name in output_names:
            result_src = scratch_dir / name
            result_dst = original_data_dir / name
            print(f"\n[Copy back] {result_src}  →  {result_dst}")
            if result_src.exists():
                if result_dst.exists():
                    shutil.rmtree(result_dst)
                shutil.copytree(result_src, result_dst)
                print(f"      Done.")
            else:
                print(f"      WARNING: expected output folder not found in scratch: {result_src}")
        if not args.keep_work_dir:
            shutil.rmtree(scratch_dir, ignore_errors=True)
            print(f"      Scratch cleaned: {scratch_dir}")
        out_root = original_data_dir
    else:
        out_root = data_dir

    print(f"\n✓ Pipeline complete.  {len(output_names)} session(s) in: {out_root.resolve()}")
    for name in output_names:
        print(f"    {out_root / name}")
    print()


def main():
    args = parse_args()

    # ── Resolve data directory ────────────────────────────────────────────────
    data_dir = args.data_dir if args.data_dir else Path.cwd()
    data_dir = data_dir.resolve()
    if not data_dir.is_dir():
        sys.exit(f"ERROR: data directory does not exist: {data_dir}")

    # ── Resolve AnimalID ──────────────────────────────────────────────────────
    animal_id = args.animal_id or infer_animal_id(data_dir)

    # ── Resolve sample rate ───────────────────────────────────────────────────
    if args.sample_rate:
        sample_rate = args.sample_rate
        sr_source   = "command line"
    else:
        # Try any immediate subdirectory's info.rhd before rename_copy moves things
        sample_rate = None
        for d in sorted(data_dir.iterdir()):
            if d.is_dir():
                rhd = d / "info.rhd"
                if rhd.exists():
                    try:
                        sample_rate = int(round(read_sample_rate(rhd)))
                        sr_source   = f"info.rhd ({d.name}/info.rhd)"
                    except Exception:
                        pass
                    break
        if sample_rate is None:
            sample_rate = cfg.DEFAULT_SAMPLE_RATE
            sr_source   = f"config default"

    # ── Resolve scratch / work directory ─────────────────────────────────────
    # Command-line flag takes precedence over config.py default.
    work_dir = args.work_dir or (Path(cfg.WORK_DIR) if cfg.WORK_DIR else None)
    original_data_dir = data_dir
    scratch_dir: "Path | None" = None

    if work_dir:
        scratch_dir = (work_dir / data_dir.name).resolve()

    print(f"\n{'='*60}")
    print(f"  Intan Pre-Processing Pipeline")
    print(f"  AnimalID    : {animal_id}")
    print(f"  Data dir    : {data_dir}")
    if scratch_dir:
        print(f"  Scratch dir : {scratch_dir}")
    print(f"  Sample rate : {sample_rate} Hz  ({sr_source})")
    print(f"  Sorting     : {'SKIPPED' if args.skip_sorting else f'KiloSort 4 → {args.output_format}'}")
    print(f"  Concatenate : {'NO (per-session sorting)' if args.no_concatenate else 'YES (merged into one session)'}")
    print(f"  LFP (.eeg)  : {'SKIPPED (--skip-lfp)' if args.skip_lfp else 'Process_LFPfromDat'}")
    print(f"  Sleep score : {'SleepScoreMaster' if args.sleep_score else 'skipped (opt-in with --sleep-score)'}")
    print(f"  NWB         : {'nwb-builder (_dirtyClusters.nwb)' if args.make_nwb else 'skipped (opt-in with --make-nwb)'}")
    print(f"  Dry run     : {args.dry_run}")
    print(f"{'='*60}\n")

    # ── Step 0 (optional): copy session data to scratch drive ─────────────────
    if scratch_dir:
        print("[0/9] Copying session data to scratch directory...")
        session_pattern = re.compile(
            r"^" + re.escape(animal_id) + r"_\d{6}_\d{6}$"
        )
        if not args.dry_run:
            scratch_dir.mkdir(parents=True, exist_ok=True)
            n_copied = 0
            for item in data_dir.iterdir():
                if item.is_dir() and session_pattern.match(item.name):
                    dst = scratch_dir / item.name
                    if dst.exists():
                        print(f"      Already present, skipping copy: {item.name}")
                    else:
                        print(f"      Copying {item.name} ...")
                        shutil.copytree(item, dst)
                    n_copied += 1
            # Copy optional support files that the pipeline may need
            for fname in ("amplifier.xml", "probe.json"):
                src = data_dir / fname
                if src.exists():
                    shutil.copy2(src, scratch_dir / fname)
            if n_copied == 0:
                sys.exit("ERROR: No session folders found to copy – nothing to do.")
            print(f"      {n_copied} session folder(s) copied.")
        else:
            hits = [d for d in data_dir.iterdir()
                    if d.is_dir() and session_pattern.match(d.name)]
            total_mb = sum(
                sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
                for d in hits
            ) / 1e6
            print(f"    [dry] Would copy {len(hits)} session folder(s) "
                  f"({total_mb:.0f} MB) → {scratch_dir}")
        data_dir = scratch_dir

    os.chdir(data_dir)          # all relative paths in sub-modules are from here

    # ── Step 1: Rename, reorganise session folders ────────────────────────────
    print("[1/9] Renaming and reorganising session folders...")
    rec_list, durations, merge_name = rename_copy_intan(
        animal_id, dry_run=args.dry_run, sample_rate=sample_rate)

    if not rec_list:
        sys.exit("ERROR: No session folders found – nothing to do.")

    print(f"      Sessions found : {len(rec_list)}")
    print(f"      Merge name     : {merge_name}")

    if args.no_concatenate:
        _run_per_session(args, rec_list, durations, data_dir, sample_rate)
        _copy_back_and_finish(
            args, scratch_dir, original_data_dir,
            output_names=rec_list, data_dir=data_dir,
        )
        return

    # ── Step 2: Build Epoch_TS.csv ────────────────────────────────────────────
    print("\n[2/9] Building Epoch_TS.csv...")
    epoch_path = build_epoch_ts(durations, dry_run=args.dry_run)
    print(f"      Written: {epoch_path}")

    # ── Step 3: Concatenate .dat files ────────────────────────────────────────
    print("\n[3/9] Concatenating .dat files...")
    merged_dat = concatenate_dat_files(rec_list, merge_name, dry_run=args.dry_run)
    print(f"      Output : {merged_dat}")

    # ── Step 4: Create / resolve output folder and move files ────────────────
    # If the root data folder is already named after the merge basename we use
    # it directly instead of creating a subfolder.
    root_matches = (data_dir.name == merge_name)
    out_dir = data_dir if root_matches else data_dir / merge_name

    if root_matches:
        print(f"\n[4/9] Root folder matches merge name — using it as output folder.")
    else:
        print(f"\n[4/9] Creating output folder and moving ancillary files...")
        if not args.dry_run:
            out_dir.mkdir(exist_ok=True)

    move_ancillary_files(
        rec_list, merge_name, epoch_path,
        dry_run=args.dry_run,
        keep_analogin=not args.no_analogin,
        keep_digitalin=not args.no_digitalin,
        keep_auxiliary=not args.no_auxiliary,
    )

    # ── Step 5: XML parameter file ────────────────────────────────────────────
    print("\n[5/9] Resolving XML parameter file...")
    src_xml = Path(f"{rec_list[0]}.xml")
    dst_xml = out_dir / f"{merge_name}.xml"

    if not args.dry_run and not dst_xml.exists():
        import json as _json

        # 1. XML in session folder (moved to flat file by rename_copy)
        if src_xml.exists():
            shutil.copy2(src_xml, dst_xml)
            print(f"      XML copied from session folder: {dst_xml.name}")

        # 2. amplifier.xml placed manually in data_dir or its parent
        else:
            for xml_candidate in [
                data_dir / "amplifier.xml",
                data_dir.parent / "amplifier.xml",
            ]:
                if xml_candidate.exists():
                    shutil.copy2(xml_candidate, dst_xml)
                    print(f"      XML copied from {xml_candidate}: {dst_xml.name}")
                    break

        # 3. No XML found — try to generate from a probe file
        if not dst_xml.exists() and not args.skip_sorting:
            probe_path = _find_probe_json(args.probe or [], data_dir)
            if probe_path is not None:
                with open(probe_path) as _f:
                    probe = _json.load(_f)
                n_total, groups = _groups_from_probe(probe)
                generate_xml(dst_xml, n_channels=n_total,
                             sample_rate=sample_rate, groups=groups)
                print(f"      XML generated from probe file '{probe_path.name}' "
                      f"({n_total} ch, {len(groups)} shank(s)).")
                print(f"      NOTE: channel groups are assigned sequentially "
                      f"({probe['n_channels_per_shank']} ch/shank).  "
                      f"Verify this matches your wiring before trusting sort results.")
            else:
                sys.exit(
                    "\nERROR: No XML parameter file and no probe file found.\n"
                    "Spike sorting requires one of the following:\n"
                    "  • An amplifier.xml in one of the session folders, in\n"
                    f"    {data_dir}, or in {data_dir.parent}\n"
                    f"  • A probe.json in {data_dir}\n"
                    "  • A --probe <name_or_path> argument pointing to a probe JSON\n"
                    "Use --skip-sorting to pre-process without sorting."
                )

    if dst_xml.exists() and not args.dry_run:
        update_xml_spk_grps(dst_xml,
                            n_samples=cfg.SPIKE_N_SAMPLES,
                            peak_sample_index=cfg.SPIKE_PEAK_SAMPLE,
                            n_features=cfg.SPIKE_N_FEATURES)
        print(f"      XML ready: {dst_xml}")

    # ── Step 6: Launch SpikeSorter ────────────────────────────────────────────
    if args.skip_sorting:
        print("\n[6/9] Spike sorting skipped (--skip-sorting flag).")
    else:
        print(f"\n[6/9] Running SpikeSorter (KiloSort 4 → {args.output_format})...")
        _run_spike_sorter(
            merge_name    = merge_name,
            data_dir      = out_dir,
            output_format = args.output_format,
            probe_names   = args.probe or [],
            layout        = args.layout,
            site_spacing  = args.site_spacing,
            dry_run       = args.dry_run,
        )
        _backup_original_clu_files(out_dir, merge_name, dry_run=args.dry_run)

    # ── Steps 7-8: LFP downsampling (default on) + sleep scoring (opt-in) ────
    print(f"\n[7/9] LFP downsampling: "
          f"{'SKIPPED (--skip-lfp)' if args.skip_lfp else f'Process_LFPfromDat → {merge_name}.eeg'}")
    print(f"[8/9] Sleep scoring: "
          f"{f'SleepScoreMaster → {merge_name}.SleepState.states.mat' if args.sleep_score else 'skipped (opt-in with --sleep-score)'}")
    run_lfp_sleep(
        base_path        = out_dir,
        skip_lfp         = args.skip_lfp,
        skip_sleep_score = not args.sleep_score,
        dry_run          = args.dry_run,
    )

    # ── Step 9: Build .nwb file (opt-in) ──────────────────────────────────────
    if args.make_nwb:
        print(f"\n[9/9] Building NWB file  →  {merge_name}_dirtyClusters.nwb ...")
        _build_nwb(out_dir, merge_name, dry_run=args.dry_run)
    else:
        print("\n[9/9] NWB build skipped (opt-in with --make-nwb).")

    # ── Cleanup: remove intermediate per-session folders and flat files ───────
    if not args.dry_run:
        for rec in rec_list:
            rec_dir = Path(rec)
            if rec_dir.is_dir():
                shutil.rmtree(rec_dir, ignore_errors=True)
            for ext in (".dat", ".xml", ".nrs", ".csv"):
                f = data_dir / f"{rec}{ext}"
                if f.exists():
                    f.unlink()
        print("\nIntermediate session files and folders removed.")

    # ── Copy results back from scratch and clean up ───────────────────────────
    if scratch_dir and not args.dry_run:
        result_src = scratch_dir / merge_name
        result_dst = original_data_dir / merge_name
        print(f"\n[Copy back] Copying output from scratch to original location...")
        print(f"      {result_src}  →  {result_dst}")
        if result_src.exists():
            if result_dst.exists():
                shutil.rmtree(result_dst)
            shutil.copytree(result_src, result_dst)
            print(f"      Done.")
        else:
            print(f"      WARNING: expected output folder not found in scratch: {result_src}")
        if not args.keep_work_dir:
            shutil.rmtree(scratch_dir, ignore_errors=True)
            print(f"      Scratch cleaned: {scratch_dir}")
        out_dir = result_dst

    print(f"\n✓ Pipeline complete.  Output in: {out_dir.resolve()}\n")

    # ── Warn if root folder name doesn't match and offer to rename ────────────
    # (Only relevant when processing in-place; skip when a scratch dir was used.)
    if not scratch_dir and not root_matches and not args.dry_run:
        print(f"  WARNING: the data folder is named '{original_data_dir.name}' "
              f"but the merge basename is '{merge_name}'.")
        print(f"  Consider renaming it to '{merge_name}' for consistency.")
        answer = input(f"  Rename '{original_data_dir.name}' → '{merge_name}' now? [y/N] ").strip().lower()
        if answer == "y":
            new_path = original_data_dir.parent / merge_name
            os.chdir(original_data_dir.parent)   # must leave the folder before renaming it
            original_data_dir.rename(new_path)
            print(f"  Renamed: {original_data_dir}  →  {new_path}")


if __name__ == "__main__":
    main()
