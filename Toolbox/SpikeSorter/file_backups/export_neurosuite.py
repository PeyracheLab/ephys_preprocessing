"""
export_neurosuite.py
====================
Converts KiloSort 4 output to Neurosuite format (Klusters / NeuroScope).

Output per spike group N (1-indexed shank number):
  {base}.res.N   ASCII  spike times in samples, sorted ascending
  {base}.clu.N   ASCII  cluster IDs (first line = number of clusters)
  {base}.spk.N   binary int16  waveforms: n_spikes × (n_chan × n_samples)
  {base}.fet.N   ASCII  features per spike (see below)

Waveforms
---------
Extracted from the raw .dat file (memory-mapped) around each spike time.
Median subtraction is applied per channel per spike (same as MATLAB wrapper).

Features (.fet format)
----------------------
Standard shanks (n_chan <= LARGE_SHANK_THRESHOLD, default 16):

  columns = [PC1_ch0 PC2_ch0 PC3_ch0  PC1_ch1 PC2_ch1 PC3_ch1  ...   (3 PCs × n_chan, channel-major)
              wvpower  wvtrough2peak                                    (2 cols, overall)
              timestamp]                                                (1 col, last)
  total = 3 × n_chan + 3

  PC ordering is channel-major: all 3 PCs for channel 0 first, then all 3
  PCs for channel 1, etc.  This matches the original MATLAB convention.
  KS4 may export more than 3 PCs; only the first cfg.SPIKE_N_FEATURES are used.

Large shanks (n_chan > LARGE_SHANK_THRESHOLD):

  columns = [wvpower   wvtrough2peak   timestamp]
  total = 3

  Per-channel PCA is skipped because large feature matrices crash Klusters.

PC features are computed by per-channel PCA on the extracted waveforms
(covariance-based, using up to 50 000 random spikes to estimate the basis).
KS4's pc_features.npy stores residual projections relative to each template's
mean — those are not suitable for Klusters (PC1 does not correlate with
spike amplitude in the expected way).
All feature values are scaled ×100 and written as integers, except the
timestamp which is written as-is.
"""

from pathlib import Path
from typing import List, Optional

import numpy as np

from . import config as cfg
from .xml_tools import XmlParams, ChannelGroup


# ─────────────────────────────────────────────────────────────────────────────
#  Public entry point
# ─────────────────────────────────────────────────────────────────────────────

def export_to_neurosuite(
    ks_dir:     Path,
    dat_path:   Path,
    params:     XmlParams,
    output_dir: Path,
    merge_name: str,
    dry_run:    bool = False,
) -> None:
    """
    Convert KiloSort 4 results to Neurosuite format.

    Parameters
    ----------
    ks_dir      : kilosort4/ results directory
    dat_path    : path to the merged broadband .dat file
    params      : parsed XML parameters
    output_dir  : directory to write Neurosuite files into
    merge_name  : base name for output files (e.g. 'KMM43-260311')
    dry_run     : print what would be done without writing files
    """
    ks_dir     = Path(ks_dir)
    dat_path   = Path(dat_path)
    output_dir = Path(output_dir)

    if dry_run:
        print("  [dry] Would export KiloSort 4 results to Neurosuite format")
        spk_grps = _resolve_spike_groups(params)
        for sh_idx, grp in enumerate(spk_grps):
            print(f"    [dry] Would write {merge_name}.res/clu/spk/fet.{sh_idx + 1}  "
                  f"({len(grp.channels)} channels)")
        return

    # ── Load KS4 results ──────────────────────────────────────────────────────
    print("  Loading KiloSort 4 results...")
    spike_times    = np.load(ks_dir / "spike_times.npy").flatten().astype(np.int64)
    spike_clusters = np.load(ks_dir / "spike_clusters.npy").flatten().astype(np.int32)
    spike_tmpls    = np.load(ks_dir / "spike_templates.npy").flatten().astype(np.int32)
    templates      = np.load(ks_dir / "templates.npy").astype(np.float32)
    amplitudes     = np.load(ks_dir / "amplitudes.npy").flatten().astype(np.float32)
    channel_map    = np.load(ks_dir / "channel_map.npy").flatten().astype(np.int32)

    n_total    = params.n_channels
    n_ks_chan  = templates.shape[2]

    # ── Resolve spike groups ──────────────────────────────────────────────────
    spk_grps = _resolve_spike_groups(params)
    if not spk_grps:
        print("  WARNING: No spike groups found in XML – skipping Neurosuite export")
        return

    # ── Map clusters to shanks ────────────────────────────────────────────────
    cluster_to_shank = _map_clusters_to_shanks(
        spike_clusters, spike_tmpls, templates, channel_map, spk_grps
    )

    output_dir.mkdir(parents=True, exist_ok=True)

    # ── Memory-map the raw .dat ───────────────────────────────────────────────
    if not dat_path.exists():
        raise FileNotFoundError(f"Raw .dat not found for waveform extraction: {dat_path}")
    dat_flat = np.memmap(dat_path, dtype="int16", mode="r")
    dat = dat_flat.reshape(-1, n_total)   # (n_samples_total, n_channels)

    # ── Process each shank ────────────────────────────────────────────────────
    for sh_idx, grp in enumerate(spk_grps):
        shank_n = sh_idx + 1

        shank_cluster_ids = {c for c, s in cluster_to_shank.items() if s == sh_idx}
        if not shank_cluster_ids:
            print(f"  Shank {shank_n}: no spikes – skipping")
            continue

        mask      = np.isin(spike_clusters, list(shank_cluster_ids))
        sh_times  = spike_times[mask]
        sh_clus   = spike_clusters[mask]
        sh_tmpls  = spike_tmpls[mask]

        sort_idx  = np.argsort(sh_times, kind="stable")
        sh_times  = sh_times[sort_idx]
        sh_clus   = sh_clus[sort_idx]
        sh_tmpls  = sh_tmpls[sort_idx]

        n_spikes    = len(sh_times)
        n_clusters  = len(np.unique(sh_clus))
        shank_chans = grp.channels          # original channel indices (0-based)
        n_shank_ch  = len(shank_chans)

        n_samples  = grp.n_samples         or cfg.SPIKE_N_SAMPLES
        peak_idx   = grp.peak_sample_index or cfg.SPIKE_PEAK_SAMPLE
        sbefore    = peak_idx
        safter     = n_samples - peak_idx

        print(f"  Shank {shank_n}: {n_spikes} spikes, {n_clusters} clusters, "
              f"{n_shank_ch} channels  (sbefore={sbefore}, safter={safter})")

        # ── .res.N ────────────────────────────────────────────────────────────
        res_path = output_dir / f"{merge_name}.res.{shank_n}"
        np.savetxt(res_path, sh_times, fmt="%d")

        # ── .clu.N ────────────────────────────────────────────────────────────
        clu_path = output_dir / f"{merge_name}.clu.{shank_n}"
        with open(clu_path, "w") as f:
            f.write(f"{n_clusters}\n")
            for c in sh_clus:
                f.write(f"{c}\n")

        # ── Extract waveforms from raw .dat ───────────────────────────────────
        waveforms = _extract_waveforms(
            dat, sh_times, shank_chans, n_total, sbefore, safter
        )
        # waveforms: (n_spikes, n_shank_ch, n_samples)

        # ── .spk.N ────────────────────────────────────────────────────────────
        # Neurosuite format: sample-major interleave, same as .dat
        # Layout per spike: (n_samples, n_channels) in C order
        # i.e. [t0_ch0, t0_ch1, ..., t0_chK, t1_ch0, ..., tN_chK]
        # waveforms is (n_spikes, n_chan, n_samples) → transpose axes 1&2 before writing
        spk_path = output_dir / f"{merge_name}.spk.{shank_n}"
        waveforms.transpose(0, 2, 1).astype(np.int16).tofile(spk_path)

        # ── Build features (per-channel PCA on extracted waveforms) ──────────
        # KS4's pc_features.npy stores residual projections (deviation from
        # template mean), not absolute waveform PCA.  Using them directly in
        # Klusters produces features uncorrelated with spike amplitude.
        # We always recompute PCA from the extracted waveforms.
        pc_fets = _compute_svd_features(waveforms, n_pcs=cfg.SPIKE_N_FEATURES)
        # pc_fets: (n_spikes, n_pcs, n_shank_ch)

        # ── .fet.N ────────────────────────────────────────────────────────────
        fet_path = output_dir / f"{merge_name}.fet.{shank_n}"
        _write_fet(fet_path, pc_fets, waveforms, sh_times)

    print(f"  Neurosuite files written to: {output_dir}")


# ─────────────────────────────────────────────────────────────────────────────
#  Cluster → shank assignment
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_spike_groups(params: XmlParams) -> List[ChannelGroup]:
    if params.spk_grps:
        return params.spk_grps
    if params.anat_grps:
        grps = []
        for ag in params.anat_grps:
            channels = [ch for ch, sk in zip(ag.channels, ag.skip) if sk == 0]
            if channels:
                grps.append(ChannelGroup(channels=channels))
        return grps
    return []


def _map_clusters_to_shanks(
    spike_clusters: np.ndarray,
    spike_tmpls:    np.ndarray,
    templates:      np.ndarray,
    channel_map:    np.ndarray,
    spk_grps:       List[ChannelGroup],
) -> dict:
    """Return {cluster_id: shank_index (0-based)}."""
    chan_to_shank: dict = {}
    for sh_idx, grp in enumerate(spk_grps):
        for ch in grp.channels:
            chan_to_shank[ch] = sh_idx

    result: dict = {}
    for c in np.unique(spike_clusters):
        mask      = spike_clusters == c
        tmpl_idx  = int(np.argmax(np.bincount(spike_tmpls[mask],
                                               minlength=templates.shape[0])))
        tmpl      = templates[tmpl_idx]                           # (T, n_ks_chan)
        peak_ks   = int(np.argmax(np.max(np.abs(tmpl), axis=0)))
        orig_ch   = int(channel_map[peak_ks])
        result[int(c)] = chan_to_shank.get(orig_ch, 0)

    return result


# ─────────────────────────────────────────────────────────────────────────────
#  Waveform extraction from raw .dat
# ─────────────────────────────────────────────────────────────────────────────

def _extract_waveforms(
    dat:         np.ndarray,
    spike_times: np.ndarray,
    shank_chans: List[int],
    n_total:     int,
    sbefore:     int,
    safter:      int,
) -> np.ndarray:
    """
    Extract spike waveforms from the memory-mapped .dat file.

    Returns float32 array of shape (n_spikes, n_shank_channels, n_samples).
    Applies per-spike median subtraction across samples (per channel).
    Spikes too close to file boundaries are returned as zeros.
    """
    n_spikes   = len(spike_times)
    n_shank_ch = len(shank_chans)
    n_samples  = sbefore + safter
    n_dat      = dat.shape[0]

    waveforms = np.zeros((n_spikes, n_shank_ch, n_samples), dtype=np.float32)

    for i, t in enumerate(spike_times):
        t = int(t)
        start = t - sbefore
        end   = t + safter
        if start < 0 or end > n_dat:
            continue    # boundary → leave as zeros

        w = dat[start:end, shank_chans].astype(np.float32)   # (n_samples, n_shank_ch)
        # median subtract per channel
        w -= np.median(w, axis=0)
        waveforms[i] = w.T   # → (n_shank_ch, n_samples)

    return waveforms


# ─────────────────────────────────────────────────────────────────────────────
#  Feature extraction
# ─────────────────────────────────────────────────────────────────────────────

def _load_pc_features(ks_dir: Path):
    """
    Load KS4 PC features, truncated to cfg.SPIKE_N_FEATURES PCs.
    Returns (pc_features, pc_feature_ind) or (None, None).
    KS4 may output more PCs than needed (e.g. 6); we only use the first 3.
    """
    feat_path = ks_dir / "pc_features.npy"
    ind_path  = ks_dir / "pc_feature_ind.npy"
    if feat_path.exists() and ind_path.exists():
        pc = np.load(feat_path)          # (n_spikes, n_ks_pcs, n_template_channels)
        n_keep = cfg.SPIKE_N_FEATURES
        if pc.shape[1] > n_keep:
            print(f"  pc_features: using first {n_keep} of {pc.shape[1]} PCs.")
            pc = pc[:, :n_keep, :]
        return pc, np.load(ind_path).astype(np.int32)
    print("  pc_features.npy not found – falling back to SVD-based PCA.")
    return None, None


def _extract_ks_pc_features(
    sh_tmpls:       np.ndarray,
    sh_pc_features: np.ndarray,
    pc_feature_ind: np.ndarray,
    shank_chans:    List[int],
    channel_map:    np.ndarray,
) -> np.ndarray:
    """
    Reorder KS4 PC features to match shank channel order.

    sh_pc_features : (n_spikes, n_pcs, n_template_channels)
    pc_feature_ind : (n_templates, n_template_channels) — KS channel indices
    Returns        : (n_spikes, n_pcs, n_shank_channels)
    """
    n_spikes   = len(sh_tmpls)
    n_pcs      = sh_pc_features.shape[1]
    n_shank_ch = len(shank_chans)

    orig_to_sh = {ch: i for i, ch in enumerate(shank_chans)}
    fets = np.zeros((n_spikes, n_pcs, n_shank_ch), dtype=np.float64)

    for tmpl_idx in np.unique(sh_tmpls):
        t_mask    = sh_tmpls == tmpl_idx
        t_pc_chs  = pc_feature_ind[tmpl_idx]           # KS channel indices

        for ks_ci, ks_ch in enumerate(t_pc_chs):
            orig_ch = int(channel_map[ks_ch]) if ks_ch < len(channel_map) else -1
            if orig_ch in orig_to_sh:
                sh_ci = orig_to_sh[orig_ch]
                fets[t_mask, :, sh_ci] = sh_pc_features[t_mask, :, ks_ci]

    return fets


def _compute_svd_features(
    waveforms: np.ndarray,
    n_pcs: int = 3,
    n_basis: int = 50_000,
) -> np.ndarray:
    """
    Per-channel PCA on extracted waveforms.  Returns (n_spikes, n_pcs, n_shank_channels).

    PCA basis vectors are estimated from a random subset of up to n_basis spikes
    via a 32×32 covariance matrix SVD (fast regardless of n_spikes).  All spikes
    are then projected onto those basis vectors.

    This produces features whose PC1 correlates with spike amplitude on each
    channel, as expected by Klusters.
    """
    n_spikes, n_shank_ch, n_samples = waveforms.shape
    fets = np.zeros((n_spikes, n_pcs, n_shank_ch), dtype=np.float32)

    if n_spikes < 2:
        return fets

    rng = np.random.default_rng(42)
    n_basis = min(n_basis, n_spikes)
    basis_idx = rng.choice(n_spikes, n_basis, replace=False)

    for ch in range(n_shank_ch):
        ch_wf = waveforms[:, ch, :].astype(np.float64)   # (n_spikes, n_samples)

        # PCA basis from random subset — SVD of (n_samples × n_samples) covariance
        basis   = ch_wf[basis_idx]
        mean_wf = basis.mean(axis=0)
        cb      = basis - mean_wf
        cov     = (cb.T @ cb) / n_basis          # (n_samples, n_samples)
        _, _, Vt = np.linalg.svd(cov, full_matrices=False)
        V = Vt[:n_pcs].T                         # (n_samples, n_pcs)

        # Project all spikes
        fets[:, :n_pcs, ch] = ((ch_wf - mean_wf) @ V).astype(np.float32)

    return fets


# ─────────────────────────────────────────────────────────────────────────────
#  .fet file writer
# ─────────────────────────────────────────────────────────────────────────────

def _write_fet(
    path:       Path,
    pc_fets:    np.ndarray,
    waveforms:  np.ndarray,
    timestamps: np.ndarray,
) -> None:
    """
    Write a Neurosuite .fet file.

    Standard shanks (n_chan <= LARGE_SHANK_THRESHOLD):
      Layout per spike (×100 scaled integers + unscaled timestamp):
        PC1_ch0 PC2_ch0 PC3_ch0  PC1_ch1 PC2_ch1 PC3_ch1  ...   channel-major
        wvpower   wvtrough2peak
        timestamp
      Total columns = 3 × n_chan + 3.

    Large shanks (n_chan > LARGE_SHANK_THRESHOLD):
      Layout per spike:
        wvpower   wvtrough2peak   timestamp
      Total columns = 3.

    First line of file = total number of columns.
    """
    n_spikes, n_shank_ch, _ = waveforms.shape
    wv_flat = waveforms.reshape(n_spikes, -1)   # (n_spikes, n_chan * n_samples)

    # ── Overall features (used in both paths) ─────────────────────────────────
    # wvpow: RMS amplitude across all channels and samples.
    # Using sum-of-squares (unnormalized) produces values ~10^6–10^9 in ADC
    # counts^2, orders of magnitude larger than PCA projections and completely
    # distorting the Klusters feature space.  RMS keeps wvpow on the same
    # scale as the PC features (~10–10000 ADC counts).
    n_feat       = wv_flat.shape[1]                               # n_chan * n_samples
    wvpow        = np.sqrt(np.sum(wv_flat ** 2, axis=1) / n_feat) # (n_spikes,)
    wvtrough2peak = wv_flat.max(axis=1) - wv_flat.min(axis=1)     # (n_spikes,)

    if n_shank_ch > cfg.LARGE_SHANK_THRESHOLD:
        # ── Large shank: energy + trough-to-peak only ─────────────────────────
        feat_int     = np.round(
            np.column_stack([wvpow, wvtrough2peak]) * 100
        ).astype(np.int64)
        n_feat_total = 3   # energy + trough2peak + timestamp

    else:
        # ── Standard shank: channel-major PCA + energy + trough-to-peak ───────
        # pc_fets shape: (n_spikes, n_pcs, n_shank_ch)
        # Channel-major: [PC1_ch0, PC2_ch0, PC3_ch0, PC1_ch1, ...]
        pcs = pc_fets.transpose(0, 2, 1).reshape(n_spikes, -1)
        # (n_spikes, n_shank_ch * n_pcs)

        feat_int = np.round(
            np.column_stack([pcs, wvpow, wvtrough2peak]) * 100
        ).astype(np.int64)
        n_feat_total = feat_int.shape[1] + 1   # +1 for timestamp

    with open(path, "w") as f:
        f.write(f"{n_feat_total}\n")
        for i in range(n_spikes):
            feat_str = "\t".join(str(v) for v in feat_int[i])
            f.write(f"{feat_str}\t{timestamps[i]}\n")
