from __future__ import annotations

import argparse
import sys

from .build_nwb import BuildConfig, build


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="nwb-build",
        description=(
            "Build an NWB file for one recording session (a folder containing "
            "the .xml, Epoch_TS.csv, .clu/.res, and per-epoch Optitrack csv / "
            "analogin.dat files). The .nwb is written into that same folder, "
            "named <folder>.nwb, unless --output is given."
        ),
    )
    p.add_argument("session_dir", help="Path to the session folder (e.g. .../B6312_260911/B6312-260911)")
    p.add_argument("-o", "--output", dest="output_path", default=None,
                    help="Output .nwb path (default: <session_dir>/<basename>.nwb)")
    p.add_argument("--force", action="store_true", help="Overwrite the output file if it already exists")
    p.add_argument("--dry-run", action="store_true",
                    help="Parse everything and print a summary, but do not write the .nwb file")
    p.add_argument("--no-position", dest="skip_position", action="store_true",
                    help="Skip Position/CompassDirection entirely (e.g. broken/missing TTL sync). "
                         "Spikes and epochs are still written.")

    tracking = p.add_argument_group("tracking / TTL sync")
    tracking.add_argument("--tracking-frequency", type=float, default=None,
                           help="Optitrack capture frame rate in Hz (default: read from the csv header)")
    tracking.add_argument("--ttl-threshold", type=float, default=0.3,
                           help="Normalized peak height threshold for TTL detection (default: 0.3)")
    tracking.add_argument("--mismatch-warn-frac", type=float, default=0.01,
                           help="Warn if |TTL count - frame count| exceeds this fraction of the larger count")

    epoch = p.add_argument_group("epochs")
    epoch.add_argument("--epoch-labels", default=None,
                        help="Comma-separated labels for each epoch in Epoch_TS.csv order "
                             "(default: epoch0, epoch1, ...)")

    subject = p.add_argument_group("subject metadata")
    subject.add_argument("--subject-id", default=None, help="Default: parsed from the folder name")
    subject.add_argument("--species", default="Mus musculus")
    subject.add_argument("--sex", default="U")
    subject.add_argument("--genotype", default="")
    subject.add_argument("--subject-description", default="")
    subject.add_argument("--age", default=None, help="ISO 8601 duration, e.g. P90D")

    session = p.add_argument_group("session metadata")
    session.add_argument("--session-description", default=None)
    session.add_argument("--experimenter", default=None)
    session.add_argument("--lab", default="Peyrache Lab")
    session.add_argument("--institution", default="McGill University")
    session.add_argument("--session-start-time", default=None,
                          help="ISO 8601 datetime override, e.g. 2026-09-11T14:17:34")

    ephys = p.add_argument_group("ephys metadata")
    ephys.add_argument("--location", default="unknown",
                        help="Brain region. Single value for all shanks, or a comma-separated "
                             "list with one entry per shank.")
    ephys.add_argument("--device-name", default="silicon_probe")
    ephys.add_argument("--device-description", default="")
    ephys.add_argument("--device-manufacturer", default="")

    args = p.parse_args(argv)

    cfg = BuildConfig(
        session_dir=args.session_dir,
        output_path=args.output_path,
        force=args.force,
        dry_run=args.dry_run,
        skip_position=args.skip_position,
        tracking_frequency=args.tracking_frequency,
        ttl_threshold=args.ttl_threshold,
        mismatch_warn_frac=args.mismatch_warn_frac,
        epoch_labels=args.epoch_labels.split(",") if args.epoch_labels else None,
        subject_id=args.subject_id,
        species=args.species,
        sex=args.sex,
        genotype=args.genotype,
        subject_description=args.subject_description,
        age=args.age,
        session_description=args.session_description,
        experimenter=args.experimenter,
        lab=args.lab,
        institution=args.institution,
        session_start_time=args.session_start_time,
        location=args.location,
        device_name=args.device_name,
        device_description=args.device_description,
        device_manufacturer=args.device_manufacturer,
    )

    try:
        build(cfg)
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
