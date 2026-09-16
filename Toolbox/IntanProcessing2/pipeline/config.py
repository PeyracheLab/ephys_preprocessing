"""
config.py
=========
Central configuration for the Intan pre-processing pipeline.

Edit this file to change defaults without touching pipeline logic.
All parameters can also be overridden at the command line (see master_preprocessing.py --help).
"""

# ── SpikeSorter integration ───────────────────────────────────────────────────
# Path to the SpikeSorter package directory.
# Set to None to auto-detect as ../SpikeSorter relative to this file.
SPIKE_SORTER_PATH = None

# Name of the conda environment that has KiloSort 4 installed.
KILOSORT_CONDA_ENV = "kilosort"

# Output format for spike sorting results.
# Options: "neurosuite" (default)  |  "phy"
DEFAULT_OUTPUT_FORMAT = "neurosuite"

# Default probe name or path passed to SpikeSorter.
# Set to None to require --probe on the command line (recommended).
# Example: DEFAULT_PROBE = "neuronexus_a1x32"
DEFAULT_PROBE = None

# ── XML / spike detection parameters ─────────────────────────────────────────
# These are written into the <spikeDetection> block of the output XML,
# matching UpdateXml_SpkGrps behaviour in the MATLAB pipeline.
SPIKE_N_SAMPLES     = 32    # number of waveform samples (was 32 in KS2.5 call)
SPIKE_PEAK_SAMPLE   = 16    # index of peak sample within waveform
SPIKE_N_FEATURES    = 3     # number of PCA features per channel group

# ── Recording hardware ────────────────────────────────────────────────────────
# Sampling rate used as fallback when no XML is found.
DEFAULT_SAMPLE_RATE = 20_000    # Hz  (Intan default)
# Bit depth of raw binary files
DEFAULT_N_BITS      = 16
# LFP target sampling rate (used by Process_LFPfromDat, see MATLAB integration below)
LFP_SAMPLE_RATE     = 1_250    # Hz

# ── File handling ─────────────────────────────────────────────────────────────
# Whether to remove original session folders after processing.
ERASE_ORIGINAL_DIRS = True
# Video formats to look for (in order of preference)
VIDEO_EXTENSIONS    = [".avi", ".mpg", ".mov"]
# Whether to move digitalin.dat files into the output folder
SAVE_DIGITALIN      = True

# ── Scratch / work directory ──────────────────────────────────────────────────
# Optional path to a fast local drive (e.g. NVMe SSD) used as a scratch space.
# When set, session data is copied here before processing so that binary-file
# merging and KiloSort 4 (which is heavily I/O bound) run against fast storage.
# The final output folder is copied back to the original data directory when
# the pipeline finishes, and the scratch copy is removed automatically.
# Set to None to process in-place (default).
# Example: WORK_DIR = "D:/scratch"
WORK_DIR = None

# ── Concatenation ─────────────────────────────────────────────────────────────
# Chunk size in samples used when streaming-concatenating large .dat files.
# Increase on machines with more RAM (e.g. 1_000_000 for 8 GB+ RAM).
CONCAT_CHUNK_SAMPLES = 500_000

# ── KiloSort 4 ────────────────────────────────────────────────────────────────
# Path to the KiloSort 4 installation (conda env or git clone).
# Leave as None to auto-detect from the active Python environment.
KILOSORT4_PATH      = None

# Name of the uv-managed virtual environment that has KiloSort 4 / PyTorch
# installed (created via `uv venv PP_ENV_NAME` per the setup instructions).
# Expected location: <repo root>/<PP_ENV_NAME>  (a sibling of Toolbox/) —
# this is where `uv venv` puts it when run from the repo root, on both
# Windows and Linux/Mac.
PP_ENV_NAME = "pp_env"

# Absolute path to the python(.exe) that has KiloSort 4 installed.
# Leave as None to auto-detect PP_ENV_NAME's interpreter relative to the repo
# root (Scripts/python.exe on Windows, bin/python on Linux/Mac). Only set this
# explicitly if your env lives somewhere other than the repo-root default.
KILOSORT_PYTHON = None

# ── MATLAB integration (LFP + sleep scoring) ──────────────────────────────────
# Path to the MATLAB executable.
# Leave as None to auto-detect (checks PATH, then common Windows install locations).
# Example: r"C:\Program Files\MATLAB\R2024b\bin\matlab.exe"
MATLAB_EXECUTABLE    = None

# Toolbox roots passed to MATLAB's addpath(genpath(...)) before running scripts.
# genpath is recursive, so only top-level folders are needed.
# Leave as None to auto-detect as Toolbox/buzcode (relative to this repo) —
# this also covers Toolbox/buzcode/peyrache_edits, which lives inside it.
MATLAB_TOOLBOX_PATHS = None

# LFP downsampling parameters passed to Process_LFPfromDat.
# LFP_SAMPLE_RATE (target output Hz) is defined above under "Recording hardware".
LFP_LO_PASS = 450   # Hz — lowpass cutoff before downsampling