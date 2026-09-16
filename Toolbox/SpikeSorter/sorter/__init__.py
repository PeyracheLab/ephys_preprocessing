"""
sorter
======
SpikeSorter package: runs KiloSort 4 and exports results to Neurosuite or Phy.
"""

from pathlib import Path
from typing import List, Optional

from . import config as cfg
from .xml_tools import load_xml, XmlParams, ensure_spk_grps
from .probe_utils import build_probe_dict
from .kilosort_runner import run_kilosort4
from .export_neurosuite import export_to_neurosuite


def run_sorting(
    merge_name:    str,
    data_dir:      "Path | str",
    output_format: str        = cfg.DEFAULT_OUTPUT_FORMAT,
    probe_names:   List[str]  = None,
    layout:        str        = cfg.DEFAULT_LAYOUT,
    site_spacing:  float      = cfg.DEFAULT_SITE_SPACING,
    export_only:   bool       = False,
    dry_run:       bool       = False,
) -> None:
    """
    Run KiloSort 4 and export results.

    Parameters
    ----------
    merge_name    : base name of the merged recording (e.g. 'KMM43-260311')
    data_dir      : directory containing {merge_name}.dat and {merge_name}.xml
    output_format : 'neurosuite' (default) or 'phy'
    probe_names   : probe name(s) or path(s) — [] to auto-detect from data_dir
    layout        : fallback geometry layout if no probe file is found
    site_spacing  : fallback inter-electrode distance in µm
    export_only   : skip KiloSort 4 and re-export from existing kilosort4/ output
    dry_run       : print actions without executing
    """
    data_dir = Path(data_dir)
    xml_path = data_dir / f"{merge_name}.xml"
    dat_path = data_dir / f"{merge_name}.dat"

    # ── Load recording parameters ──────────────────────────────────────────
    params: Optional[XmlParams] = None
    if xml_path.exists():
        params = load_xml(xml_path)
    else:
        print(f"  WARNING: {xml_path} not found – using config defaults")
        params = XmlParams(n_channels=0, sample_rate=cfg.DEFAULT_SAMPLE_RATE)

    # ── Resolve probe names (config default if nothing passed) ─────────────
    if probe_names is None:
        probe_names = [cfg.DEFAULT_PROBE] if cfg.DEFAULT_PROBE else []

    # ── Ensure XML has complete spike detection block ──────────────────────
    if xml_path.exists() and not dry_run:
        ensure_spk_grps(
            xml_path,
            n_samples         = cfg.SPIKE_N_SAMPLES,
            peak_sample_index = cfg.SPIKE_PEAK_SAMPLE,
            n_features        = 3,
        )
        # Reload params so spk_grps are populated for the export step
        params = load_xml(xml_path)

    # ── Build probe dict ───────────────────────────────────────────────────
    print(f"\n[SpikeSorter] Building probe configuration...")
    library_dir = Path(cfg.PROBE_LIBRARY_PATH) if cfg.PROBE_LIBRARY_PATH else None
    probe_dict = build_probe_dict(
        params       = params,
        probe_names  = probe_names,
        library_dir  = library_dir,
        layout       = layout,
        site_spacing = site_spacing,
        data_dir     = data_dir,
    )

    # ── Step 1: Run KiloSort 4 (skipped when export_only) ─────────────────
    ks_dir = data_dir / "kilosort4"
    if export_only:
        if not ks_dir.is_dir():
            raise FileNotFoundError(
                f"--export-only requires an existing kilosort4/ folder at:\n  {ks_dir}"
            )
        print(f"\n[SpikeSorter] Skipping KiloSort 4 (--export-only).")
    else:
        print(f"\n[SpikeSorter] Running KiloSort 4 on {merge_name}...")
        ks_dir = run_kilosort4(
            merge_name = merge_name,
            work_dir   = data_dir,
            probe_dict = probe_dict,
            dry_run    = dry_run,
        )

    # ── Step 2: Export results ─────────────────────────────────────────────
    if output_format == "neurosuite":
        print(f"\n[SpikeSorter] Exporting to Neurosuite format...")
        export_to_neurosuite(
            ks_dir     = ks_dir,
            dat_path   = dat_path,
            params     = params,
            output_dir = data_dir,
            merge_name = merge_name,
            dry_run    = dry_run,
        )
    elif output_format == "phy":
        print(f"\n[SpikeSorter] Output format: Phy  →  results in {ks_dir}")
    else:
        raise ValueError(
            f"Unknown output format: {output_format!r}. "
            "Choose 'neurosuite' or 'phy'."
        )

    print(f"\n[SpikeSorter] Done.")
