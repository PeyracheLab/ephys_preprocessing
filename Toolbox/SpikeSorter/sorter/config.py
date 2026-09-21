"""
config.py
=========
Central configuration for SpikeSorter.

Edit this file to change defaults without touching pipeline logic.
"""

# ── Output format ──────────────────────────────────────────────────────────────
# Options: "neurosuite"  |  "phy"
DEFAULT_OUTPUT_FORMAT = "neurosuite"

# ── Probe ──────────────────────────────────────────────────────────────────────
# Default probe name or path.  Used when --probe is not passed on the command
# line and no probe.json is found in the data folder.
# Set to None to force explicit probe specification (recommended).
DEFAULT_PROBE = None

# Path to the probe library directory.
# Set to None to auto-detect as Toolbox/Probes/ (two levels above this package).
PROBE_LIBRARY_PATH = None

# Fallback probe layout used when no probe file is available at all.
# Options: "staggered" | "linear" | "columns"
DEFAULT_LAYOUT = "staggered"

# Fallback inter-electrode distance in µm (used with DEFAULT_LAYOUT).
DEFAULT_SITE_SPACING = 20.0

# ── Recording hardware ─────────────────────────────────────────────────────────
DEFAULT_SAMPLE_RATE = 20_000    # Hz
DEFAULT_N_BITS      = 16

# ── Spike waveform parameters ──────────────────────────────────────────────────
# Used when values are absent from the XML <spikeDetection> block.
SPIKE_N_SAMPLES   = 32
SPIKE_PEAK_SAMPLE = 16
SPIKE_N_FEATURES  = 3     # number of PCs per channel written to .fet files

# ── Neurosuite feature export ──────────────────────────────────────────────────
# Shanks with more than this many channels use simplified features (overall
# energy + trough-to-peak only) instead of per-channel PCA, to avoid crashing
# Klusters with an excessive number of feature columns.
LARGE_SHANK_THRESHOLD = 16

# Waveforms are extracted and written in chunks of this many spikes at a
# time, rather than all at once, so memory use stays bounded regardless of
# how many spikes or channels a shank has (a dense, high-channel-count shank
# can easily need tens of GB if materialized in one array).
WAVEFORM_CHUNK_SPIKES = 200_000

# ── KiloSort 4 settings ────────────────────────────────────────────────────────
KS4_BATCH_SIZE = 60_000
KS4_NBLOCKS    = 1         # 1 = rigid drift correction; >1 = non-rigid
