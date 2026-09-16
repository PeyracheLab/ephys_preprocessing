"""
per_session.py
===============
Finalizes each raw Intan recording bout as its own independent,
self-contained session folder, instead of concatenating all of a day's
bouts into one merged recording (see concatenate.py for the merged path).

Used by master_preprocessing.py when run with --no-concatenate.

Before this runs, rename_copy_intan() has already produced, for each
session `rec` (e.g. 'B6312-260914-01'):

    data_dir/{rec}.dat                    (flat, main ephys data)
    data_dir/{rec}.xml                    (flat, if found)
    data_dir/{rec}.nrs                    (flat, if found)
    data_dir/{rec}.csv                    (flat, tracking csv)
    data_dir/{rec}/{rec}_analogin.dat     (if present)
    data_dir/{rec}/{rec}_digitalin.dat    (if present)
    data_dir/{rec}/{rec}_auxiliary.dat    (if present)
    data_dir/{rec}/{rec}_info.rhd
    data_dir/{rec}/{rec}.avi               (if present)

finalize_single_session() moves the flat files into data_dir/{rec}/ and
renames the per-session analogin/digitalin files to add an "_0_" epoch
suffix, so the result matches the same naming convention a single-session
merged day would produce (and what nwb-builder expects): a self-contained
folder with {rec}.dat, {rec}.xml, Epoch_TS.csv, {rec}_0.csv,
{rec}_0_analogin.dat.

IMPORTANT: unlike the merged path (concatenate.py + file_utils.py), here
data_dir/{rec}/ is BOTH where rename_copy_intan staged the ancillary files
AND the final output folder. Files are moved in place, not copied, and
this folder must NOT be deleted by the generic intermediate-folder cleanup
that the merged path runs at the end of master_preprocessing.py.
"""

from pathlib import Path

from .epoch_ts import build_epoch_ts


def finalize_single_session(
    rec: str,
    duration: float,
    data_dir: Path,
    dry_run: bool = False,
    keep_analogin: bool = True,
    keep_digitalin: bool = True,
    keep_auxiliary: bool = True,
) -> Path:
    """
    Move one session's flat/staged files into data_dir/{rec}/ as a final,
    self-contained session folder, and write its (trivial, single-epoch)
    Epoch_TS.csv.

    Returns
    -------
    Path to the finalized session folder (data_dir / rec).
    """
    out_dir = data_dir / rec

    if dry_run:
        print(f"    [dry] Finalize session folder: {out_dir}")
    else:
        out_dir.mkdir(parents=True, exist_ok=True)

    def _move(src: Path, dst: Path) -> None:
        if not src.exists():
            return
        if dry_run:
            print(f"    [dry] MOVE  {src}  ->  {dst}")
            return
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.rename(dst)

    # Main ephys .dat / .xml / .nrs: flat in data_dir -> out_dir/{rec}.*
    _move(data_dir / f"{rec}.dat", out_dir / f"{rec}.dat")
    _move(data_dir / f"{rec}.xml", out_dir / f"{rec}.xml")
    _move(data_dir / f"{rec}.nrs", out_dir / f"{rec}.nrs")

    # Tracking csv: flat in data_dir -> out_dir/{rec}_0.csv (epoch-0 suffix,
    # matching the convention used for multi-session merges).
    _move(data_dir / f"{rec}.csv", out_dir / f"{rec}_0.csv")

    # analogin / digitalin were already staged inside out_dir by
    # rename_copy_intan; just rename in place to add the epoch-0 suffix.
    if keep_analogin:
        _move(out_dir / f"{rec}_analogin.dat", out_dir / f"{rec}_0_analogin.dat")
    else:
        _delete_if_exists(out_dir / f"{rec}_analogin.dat", dry_run)

    if keep_digitalin:
        _move(out_dir / f"{rec}_digitalin.dat", out_dir / f"{rec}_0_digitalin.dat")
    else:
        _delete_if_exists(out_dir / f"{rec}_digitalin.dat", dry_run)

    if not keep_auxiliary:
        _delete_if_exists(out_dir / f"{rec}_auxiliary.dat", dry_run)
    # else: already correctly named/placed by rename_copy_intan, leave as-is.

    # Epoch_TS.csv: trivial single epoch, 0 -> duration.
    build_epoch_ts([duration], output_path=out_dir / "Epoch_TS.csv", dry_run=dry_run)

    return out_dir


def _delete_if_exists(path: Path, dry_run: bool) -> None:
    if not path.exists():
        return
    if dry_run:
        print(f"    [dry] DELETE  {path}")
    else:
        path.unlink()
