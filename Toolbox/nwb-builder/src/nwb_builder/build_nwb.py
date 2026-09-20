"""Orchestrates: xml + Epoch_TS.csv + Optitrack csv + analogin TTL + Neurosuite
spikes -> a single .nwb file for one session, following the same NWB schema
nwbmatic used (so it reads back as pynapple objects via nap.load_file / a
NeuroSuite-style loader)."""
from __future__ import annotations

import datetime
import glob
import os
import re
import sys
import warnings
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from pynwb import NWBHDF5IO, NWBFile
from pynwb.behavior import CompassDirection, Position, SpatialSeries
from pynwb.epoch import TimeIntervals
from pynwb.file import Subject

from .epochs import parse_epoch_ts
from .optitrack import load_optitrack_csv, parse_capture_frame_rate, parse_capture_start_time
from .sleep_states import load_sleep_states
from .spikes import load_neurosuite_spikes
from .ttl import load_ttl_pulse
from .xml_params import parse_xml_params


@dataclass
class BuildConfig:
    session_dir: str
    output_path: str | None = None
    force: bool = False
    dry_run: bool = False
    skip_position: bool = False  # skip Position/CompassDirection entirely (e.g. bad/missing TTL sync)

    tracking_frequency: float | None = None  # None -> read from optitrack csv header
    ttl_threshold: float = 0.3
    mismatch_warn_frac: float = 0.01  # warn if |len(ttl)-len(position)| exceeds this fraction

    epoch_labels: list[str] | None = None

    subject_id: str | None = None
    species: str = "Mus musculus"
    sex: str = "U"
    genotype: str = ""
    subject_description: str = ""
    age: str | None = None

    session_description: str | None = None
    experimenter: str | None = None
    lab: str = "Peyrache Lab"
    institution: str = "McGill University"
    session_start_time: str | None = None  # ISO string override

    location: str = "unknown"  # comma-separated, one per shank, or a single value for all
    device_name: str = "silicon_probe"
    device_description: str = ""
    device_manufacturer: str = ""


def _basename(session_dir: str) -> str:
    return os.path.basename(os.path.normpath(session_dir))


def _guess_subject_id(basename: str) -> str:
    m = re.match(r"([A-Za-z0-9]+?)[-_]\d+$", basename)
    return m.group(1) if m else basename


def _guess_session_start_time(session_dir: str, basename: str, epoch0_csv: str | None):
    local_tz = datetime.datetime.now().astimezone().tzinfo

    if epoch0_csv and os.path.exists(epoch0_csv):
        dt = parse_capture_start_time(epoch0_csv)
        if dt is not None:
            return dt.replace(tzinfo=local_tz)

    m = re.search(r"(\d{2})(\d{2})(\d{2})$", basename)
    if m:
        yy, mm, dd = m.groups()
        try:
            return datetime.datetime(2000 + int(yy), int(mm), int(dd), tzinfo=local_tz)
        except ValueError:
            pass

    xmls = glob.glob(os.path.join(session_dir, "*.xml"))
    if xmls:
        ts = os.path.getmtime(xmls[0])
        return datetime.datetime.fromtimestamp(ts, tz=local_tz)

    return datetime.datetime.now(tz=local_tz)


def _resolve_locations(location_cfg: str, n_groups: int) -> list[str]:
    parts = [p.strip() for p in location_cfg.split(",") if p.strip()]
    if len(parts) == n_groups:
        return parts
    if len(parts) == 1:
        return parts * n_groups
    warnings.warn(
        f"--location has {len(parts)} entries but there are {n_groups} shanks; "
        f"using '{location_cfg}' for all shanks."
    )
    return [location_cfg] * n_groups


def _load_position(cfg: BuildConfig, session_dir: str, basename: str, epochs, fs_dat: float):
    frames = []
    time_support_bounds = []

    for ep in epochs:
        csv_path = os.path.join(session_dir, f"{basename}_{ep.index}.csv")
        ttl_path = os.path.join(session_dir, f"{basename}_{ep.index}_analogin.dat")

        if not (os.path.exists(csv_path) and os.path.exists(ttl_path)):
            print(f"  [epoch {ep.index}:{ep.label}] no tracking data (missing csv or analogin) - skipping position")
            continue

        position_local = load_optitrack_csv(csv_path)
        tracking_frequency = cfg.tracking_frequency or parse_capture_frame_rate(csv_path)

        ttl_local = load_ttl_pulse(
            ttl_path,
            tracking_frequency=tracking_frequency,
            n_channels=1,
            channel=0,
            bytes_size=2,
            fs=fs_dat,
            threshold=cfg.ttl_threshold,
        )

        n_ttl, n_pos = len(ttl_local), len(position_local)
        if n_ttl == 0:
            warnings.warn(f"[epoch {ep.index}] no TTL pulses detected in {ttl_path}; skipping position for this epoch")
            continue

        mismatch = abs(n_ttl - n_pos)
        if mismatch > max(5, cfg.mismatch_warn_frac * max(n_ttl, n_pos)):
            warnings.warn(
                f"[epoch {ep.index}] TTL count ({n_ttl}) and Optitrack frame count ({n_pos}) "
                f"differ by {mismatch}; truncating to the shorter of the two. "
                f"Check sync quality for this epoch."
            )

        length = min(n_ttl, n_pos)
        ttl_local = ttl_local[:length]
        position_local = position_local.iloc[:length].copy()

        global_ts = ep.start + ttl_local
        position_local.index = pd.Index(global_ts, name="time")

        frames.append(position_local)
        time_support_bounds.append((global_ts[0], global_ts[-1]))

        print(f"  [epoch {ep.index}:{ep.label}] tracking: {length} frames, {tracking_frequency} Hz, "
              f"aligned to [{global_ts[0]:.3f}, {global_ts[-1]:.3f}] s")

    if not frames:
        return None, []

    position = pd.concat(frames)
    return position, time_support_bounds


def build(cfg: BuildConfig) -> str:
    session_dir = os.path.abspath(cfg.session_dir)
    if not os.path.isdir(session_dir):
        raise FileNotFoundError(f"Session directory not found: {session_dir}")
    basename = _basename(session_dir)

    output_path = cfg.output_path or os.path.join(session_dir, f"{basename}.nwb")
    if os.path.exists(output_path):
        if not cfg.force and not cfg.dry_run:
            raise FileExistsError(f"{output_path} already exists. Pass --force to overwrite.")
        if cfg.force and not cfg.dry_run:
            # Remove first rather than let HDF5 open the existing file in
            # truncate mode: on some network mounts (e.g. GVFS/FUSE SMB
            # shares) opening an existing file for truncation fails, while
            # creating a fresh one works fine.
            os.remove(output_path)

    print(f"Session dir: {session_dir}")
    print(f"Basename:    {basename}")

    xml_params = parse_xml_params(session_dir)
    print(f"XML params:  {xml_params.n_channels} channels, {xml_params.fs_dat} Hz, "
          f"{len(xml_params.group_to_channel)} shanks")

    epochs = parse_epoch_ts(session_dir, cfg.epoch_labels)
    print(f"Epochs ({len(epochs)}):")
    for ep in epochs:
        print(f"  [{ep.index}:{ep.label}] {ep.start:.3f} -> {ep.end:.3f} s "
              f"({ep.end - ep.start:.3f} s)")

    if cfg.skip_position:
        print("Tracking / TTL sync: skipped (--no-position)")
        position, position_bounds = None, []
    else:
        print("Tracking / TTL sync:")
        position, position_bounds = _load_position(cfg, session_dir, basename, epochs, xml_params.fs_dat)

    print("Spikes:")
    spikes = load_neurosuite_spikes(session_dir, basename, xml_params.fs_dat)
    n_by_group: dict[int, int] = {}
    for g in spikes.unit_group.values():
        n_by_group[g] = n_by_group.get(g, 0) + 1
    print(f"  {len(spikes.spike_times)} units across {len(n_by_group)} shanks "
          f"({dict(sorted(n_by_group.items()))})")

    sleep_states = load_sleep_states(session_dir, basename)
    if sleep_states is None:
        print("Sleep states: none found (no <basename>.SleepState.states.mat)")
    else:
        print("Sleep states: " + ", ".join(
            f"{name}={len(arr)}" for name, arr in sleep_states.items()
        ))

    if cfg.dry_run:
        print("\n--dry-run: not writing an NWB file.")
        return output_path

    epoch0_csv = os.path.join(session_dir, f"{basename}_0.csv")
    if cfg.session_start_time:
        local_tz = datetime.datetime.now().astimezone().tzinfo
        session_start_time = datetime.datetime.fromisoformat(cfg.session_start_time)
        if session_start_time.tzinfo is None:
            session_start_time = session_start_time.replace(tzinfo=local_tz)
    else:
        session_start_time = _guess_session_start_time(session_dir, basename, epoch0_csv)

    subject_id = cfg.subject_id or _guess_subject_id(basename)
    session_description = cfg.session_description or f"Electrophysiology + Optitrack session {basename}"

    nwbfile = NWBFile(
        session_description=session_description,
        identifier=basename,
        session_start_time=session_start_time,
        experimenter=[cfg.experimenter] if cfg.experimenter else None,
        lab=cfg.lab,
        institution=cfg.institution,
        subject=Subject(
            subject_id=subject_id,
            species=cfg.species,
            sex=cfg.sex,
            genotype=cfg.genotype or None,
            description=cfg.subject_description or None,
            age=cfg.age,
        ),
    )

    # --- electrodes / electrode groups -------------------------------------------------
    n_groups = len(xml_params.group_to_channel)
    locations = _resolve_locations(cfg.location, n_groups)
    electrode_groups = {}
    for g, channels in xml_params.group_to_channel.items():
        device = nwbfile.create_device(
            name=f"{cfg.device_name}-{g}",
            description=cfg.device_description or f"Shank {g}",
            manufacturer=cfg.device_manufacturer or "unknown",
        )
        electrode_groups[g] = nwbfile.create_electrode_group(
            name=f"group{g}",
            description=f"Shank {g} ({len(channels)} channels)",
            location=locations[g],
            device=device,
        )
        for ch in channels:
            nwbfile.add_electrode(
                id=int(ch),
                x=0.0, y=0.0, z=0.0, imp=0.0,
                location=locations[g],
                filtering="none",
                group=electrode_groups[g],
            )

    # --- units ---------------------------------------------------------------------
    nwbfile.add_unit_column("location", "the anatomical location of this unit")
    nwbfile.add_unit_column("group", "the shank (electrode group index) of this unit")
    for uid, t in spikes.spike_times.items():
        g = spikes.unit_group[uid]
        nwbfile.add_unit(
            id=uid,
            spike_times=t,
            electrode_group=electrode_groups[g],
            location=locations[g],
            group=g,
        )

    # --- epochs --------------------------------------------------------------------
    for ep in epochs:
        nwbfile.add_epoch(start_time=ep.start, stop_time=ep.end, tags=[ep.label])

    # --- sleep states (sws / rem / wake), one TimeIntervals table per state --------
    # Kept as separate named tables (rather than one table with a state column)
    # because pynapple's NWB reader turns each TimeIntervals table into its own
    # IntervalSet, keyed by the table's name — so nap.load_file(...)["sws"] and
    # ["rem"] come back directly as IntervalSet objects.
    if sleep_states is not None:
        for name, arr in sleep_states.items():
            ti = TimeIntervals(name=name, description=f"{name} epochs from SleepScoreMaster")
            for start, end in arr:
                ti.add_interval(start_time=float(start), stop_time=float(end))
            nwbfile.add_time_intervals(ti)

    # --- position / rotation ---------------------------------------------------------
    if position is not None:
        pos_container = Position()
        for c in ("x", "y", "z"):
            if c in position.columns:
                pos_container.add_spatial_series(SpatialSeries(
                    name=c, data=position[c].values, timestamps=position.index.values,
                    unit="", reference_frame="",
                ))
        nwbfile.add_acquisition(pos_container)

        rot_cols = [c for c in ("rx", "ry", "rz") if c in position.columns]
        if rot_cols:
            dir_container = CompassDirection()
            for c in rot_cols:
                dir_container.add_spatial_series(SpatialSeries(
                    name=c, data=position[c].values, timestamps=position.index.values,
                    unit="radian", reference_frame="",
                ))
            nwbfile.add_acquisition(dir_container)

        position_time_support = TimeIntervals(
            name="position_time_support",
            description="Real start/end of tracked position data per epoch (post TTL alignment)",
        )
        for i, (start, end) in enumerate(position_bounds):
            position_time_support.add_interval(start_time=float(start), stop_time=float(end), tags=str(i))
        nwbfile.add_time_intervals(position_time_support)

    with NWBHDF5IO(output_path, "w") as io:
        io.write(nwbfile)

    print(f"\nWrote {output_path}")
    return output_path
