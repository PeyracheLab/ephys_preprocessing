# IntanProcessing2
# Intan Pre-Processing Pipeline (Python)

Python port of `MasterPreProcessing_Intan25.m` and its dependencies.  
Original MATLAB code by Adrien Peyrache (2017).

---

## What this pipeline does

Given a folder containing multiple Intan recording sessions from a single day
(named `AnimalID_YYMMDD_HHMMSS`), the pipeline:

1. **Discovers** all session folders matching the AnimalID prefix, sorted chronologically
2. **Renames & reorganises** raw files out of the Intan session folders into flat
   intermediate files (`AnimalID-YYMMDD-NN.dat`, `.xml`, etc.)
3. **Builds `Epoch_TS.csv`** — a two-column CSV (start_sec, end_sec) marking the
   boundaries of each original recording within the merged file
4. **Concatenates** all per-session `amplifier.dat` files into a single
   `AnimalID-YYMMDD.dat` (flat int16, channels interleaved)
5. **Moves ancillary files** into the output folder:
   - `_analogin.dat`, `_digitalin.dat`, `_auxiliary.dat` (concatenated), `_time.dat`
   - Position tracking `.csv` files
   - Video files (`.avi`/`.mpg`/`.mov`)
6. **Copies & updates the XML** parameter file (`amplifier.xml` → `AnimalID-YYMMDD.xml`)
   with spike detection parameters (`nSamples`, `peakSampleIndex`, `nFeatures`)
7. **Launches** the selected spike sorter:
   - **KiloSort 4** (default) — pure Python, GPU-accelerated
   - **KiloSort 2.5** — via MATLAB subprocess (legacy support)

---

## Folder structure expected

```
Documents\TestData\KMM43-260311\          ← run the script from HERE
    KMM43_260311_093012\                  ← session 1 (Intan output folder)
        amplifier.dat
        amplifier.xml
        analogin.dat
        digitalin.dat
        auxiliary.dat
        time.dat
        info.rhd
        tracking.csv
    KMM43_260311_142205\                  ← session 2
        amplifier.dat
        ...
```

---

## Output structure

```
Documents\TestData\KMM43-260311\
    KMM43-260311\                         ← merged output folder
        KMM43-260311.dat                  ← concatenated broadband data
        KMM43-260311.xml                  ← updated Neuroscope parameter file
        Epoch_TS.csv                      ← start/end times of each session
        KMM43-260311_0_analogin.dat
        KMM43-260311_1_analogin.dat
        KMM43-260311_auxiliary.dat        ← concatenated auxiliary
        KMM43-260311_0_digitalin.dat
        KMM43-260311_0.csv                ← position CSV session 0
        kilosort4\                        ← KiloSort 4 output
            spike_times.npy
            spike_clusters.npy
            ...
```

---

## Installation

### Step 1 — Run the setup script (once)

Open an **Anaconda Prompt** and run:

```bat
cd Documents\Toolbox\IntanProcessing2
setup_env.bat
```

This creates a conda environment called `intan_proc` with:
- Python 3.10
- NumPy, SciPy, pandas, matplotlib
- PyTorch (CUDA-enabled if an NVIDIA GPU is detected)
- KiloSort 4

### Step 2 — Configure (optional)

Open `pipeline/config.py` and adjust:

| Setting | Default | Description |
|---|---|---|
| `DEFAULT_SORTER` | `"kilosort4"` | Which sorter to use |
| `SPIKE_N_SAMPLES` | `32` | Waveform samples per spike |
| `SPIKE_PEAK_SAMPLE` | `16` | Peak sample index |
| `DEFAULT_SAMPLE_RATE` | `20000` | Fallback sample rate (Hz) |
| `SAVE_DIGITALIN` | `True` | Move digitalin files |
| `MATLAB_EXECUTABLE` | `None` | Path to matlab.exe (KS2.5 only) |

---

## Usage

```bat
conda activate intan_proc
cd Documents\TestData\KMM43-260311
python Documents\Toolbox\IntanProcessing2\master_preprocessing.py KMM43
```

### Command-line options

```
positional:
  animal_id             AnimalID prefix (e.g. KMM43). Auto-detected if omitted.

optional:
  --sorter {kilosort4,kilosort2_5}
                        Spike sorter (default: kilosort4)
  --skip-sorting        Pre-process only; skip spike sorting
  --data-dir PATH       Data directory (default: current working directory)
  --dry-run             Print what would be done without doing it
```

### Examples

```bat
# Standard run (KiloSort 4)
python master_preprocessing.py KMM43

# Use KiloSort 2.5 instead
python master_preprocessing.py KMM43 --sorter kilosort2_5

# Pre-process only, no sorting
python master_preprocessing.py KMM43 --skip-sorting

# Run on a different data folder without cd-ing first
python master_preprocessing.py KMM43 --data-dir "D:\Data\KMM43-260311"

# Test run — see what would happen without touching files
python master_preprocessing.py KMM43 --dry-run
```

---

## Using KiloSort 2.5 (MATLAB)

KiloSort 2.5 is still fully supported.  Requirements:

1. MATLAB must be installed and `matlab` must be on your system PATH  
   (or set `MATLAB_EXECUTABLE` in `config.py`)
2. `KiloSort25Wrapper.m` must be on your MATLAB path
3. Run with `--sorter kilosort2_5`

---

## File format reference

- **`.dat`** — flat binary, int16, channels interleaved, row-major  
  Shape: `[n_channels × n_samples]` samples written sample-by-sample  
  Read in Python: `np.memmap(path, dtype='int16', mode='r').reshape(-1, n_channels)`
- **`.xml`** — Neuroscope/NDManager parameter file  
  See https://neurosuite.sourceforge.net/formats.html
- **`Epoch_TS.csv`** — two columns, no header: `start_sec, end_sec`
- **`time.dat`** — int32 sample indices from Intan (4 bytes/sample)

---

## Module overview

```
IntanProcessing2/
    master_preprocessing.py   ← entry point (replaces MasterPreProcessing_Intan25.m)
    setup_env.bat             ← one-time conda environment setup
    requirements.txt
    pipeline/
        config.py             ← all tunable parameters
        rename_copy.py        ← port of Process_RenameCopyIntan.m
        concatenate.py        ← port of Process_ConcatenateDatFiles.m
        xml_tools.py          ← port of LoadXml.m + UpdateXml_SpkGrps.m
        epoch_ts.py           ← Epoch_TS.csv builder
        file_utils.py         ← ancillary file mover
        sorter.py             ← KiloSort 4 + KiloSort 2.5 launcher
```
