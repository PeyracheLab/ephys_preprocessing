# ephys_preprocessing

Intan → KiloSort 4 → sleep scoring → NWB pipeline for the Peyrache Lab. Works on Linux and Windows.

## 1. Clone the repo

Linux/macOS: open a terminal. Windows: open PowerShell.

```
git clone https://github.com/PeyracheLab/ephys_preprocessing.git
cd ephys_preprocessing
```

(No git? On GitHub use the green **Code** button → **Download ZIP** instead, and unzip it.)

## 2. Set up the environment

Follow **[SETUP.md](SETUP.md)** — one-time setup of the `pp_env` environment and all Python packages. Do this before anything below.

## 3. Running `master_preprocessing.py`

The script lives at `Toolbox/IntanProcessing2/master_preprocessing.py`. Activate `pp_env` first, then run it from inside that folder.

Linux/macOS:
```
source pp_env/bin/activate
cd Toolbox/IntanProcessing2
python master_preprocessing.py B3218 --data-dir /path/to/B3218_recordings --probe Buzsaki64sp
```

Windows:
```
pp_env\Scripts\activate
cd Toolbox\IntanProcessing2
python master_preprocessing.py B3218 --data-dir D:\Data\B3218_recordings --probe Buzsaki64sp
```

### Base behavior (no optional flags)

With just an animal ID, `--data-dir`, and `--probe`, the pipeline runs these steps automatically, in order:

1. Discover the animal's raw Intan session folders
2. Rename/reorganize them into `AnimalID-YYMMDD` intermediate folders
3. Build `Epoch_TS.csv` from the session durations
4. Concatenate all sessions' `.dat` files into one merged recording
5. Copy/merge auxiliary files (analogin, digitalin, auxiliary)
6. Resolve the XML parameter file and update its spike-detection block
7. Run KiloSort 4 (via SpikeSorter), export to Neurosuite
8. Downsample the LFP to a `.eeg` file (`Process_LFPfromDat`)

**Off by default**: sleep scoring and building an `.nwb` file. Both are opt-in — see below.

### The three flags you should basically always set

- **`<animal_id>`** (positional, first argument) — e.g. `B3218`. The code *can* infer this automatically from the session folder names if you leave it out, but always pass it explicitly — it's how the pipeline knows which sessions belong together, and letting it guess is an easy way to silently pick up the wrong recordings.
- **`--data-dir PATH`** — the folder containing that animal's raw Intan session folders. Defaults to your current directory if you don't set it, but always set it explicitly so it's unambiguous exactly what data you're processing, especially when scripting multiple runs.
- **`--probe NAME_OR_PATH`** — e.g. `--probe Buzsaki64sp`, or a path to your own probe JSON. **Always include this.** The code *can* fall back to a generic layout (`--layout`/`--site-spacing`) with no `--probe` at all, but that fallback assumes every shank has an identical channel count and made-up spacing — it is never geometrically correct for real hardware. Only skip `--probe` if you genuinely don't care about spatial-aware sorting.

### Important: the XML must have one anatomical group per shank

The XML's `<anatomicalDescription>` needs **exactly one channel group per physical shank**, in the same order as the shanks in your probe file — and if shanks have *different* channel counts (e.g. one shank carrying extra deep electrodes, like `Buzsaki64sp`), each XML group's size must match that specific shank's count exactly.

### Flags worth highlighting

- **`--skip-sorting`** — pre-process only; do not run KiloSort 4 at all. Use this if you just want the merged `.dat`/`.xml`/`.eeg` ready without sorting yet.
- **`--no-concatenate`** — do not merge each day's recording bouts into one session; keep each raw bout as its own folder and spike-sort it separately.
- **`--skip-lfp`** — skip the automatic `.eeg` creation (`Process_LFPfromDat`). This step runs by default on every call; use this flag to turn it off.
- **`--sleep-score`** — opt in to automated sleep scoring (`SleepScoreMaster`) after LFP downsampling. Off by default. Requires MATLAB.
- **`--make-nwb`** — opt in to building an `.nwb` file once the pipeline finishes. Off by default. Since this runs right after automated KiloSort 4 sorting, before any manual cluster curation, the file is named `AnimalID-YYMMDD_dirtyClusters.nwb` to make that explicit. If `--sleep-score` was also used, sws/rem/wake epochs are written in as separate pynapple-readable `IntervalSet`s.

### Running sleep scoring only, or NWB only

**Sleep scoring only** — skip spike sorting entirely and just get the `.eeg` + sleep states (e.g. you want sleep architecture quickly, without waiting on KiloSort):

```
python master_preprocessing.py B3218 --data-dir /path/to/B3218_recordings --probe Buzsaki64sp --skip-sorting --sleep-score
```
(Windows: same flags, just use the Windows path/activation shown above.)

LFP downsampling still runs automatically here — sleep scoring needs the `.eeg`. Only add `--skip-lfp` on top of this if you already have a `.eeg` from an earlier run and just want to redo the scoring.

**NWB only** — build or rebuild the `.nwb` for a session you've *already* preprocessed (e.g. after manually curating clusters in Phy/Klusters, or if you forgot `--make-nwb` the first time). This doesn't go through `master_preprocessing.py` — `nwb-builder` installs its own command, `nwb-build`, directly into `pp_env`:

```
nwb-build path/to/AnimalID-YYMMDD
```

This writes `AnimalID-YYMMDD.nwb` (no `_dirtyClusters` suffix — use this once clusters are actually clean) into that same folder. Pass `--force` to overwrite an existing one. Run `nwb-build --help` for optional metadata flags (subject info, session description, brain region per shank, etc.).

### All other flags

- `--output-format {neurosuite,phy}` — spike sorting export format (default: `neurosuite`)
- `--layout {staggered,linear,columns}` — fallback probe geometry if no probe file is found (default: `staggered`)
- `--site-spacing MICRONS` — fallback inter-electrode spacing if no probe file is found (default: `20.0`)
- `--sample-rate HZ` — override the recording sample rate (auto-detected from `info.rhd` by default)
- `--no-analogin` / `--no-digitalin` / `--no-auxiliary` — exclude that auxiliary file type from the merged output
- `--work-dir PATH` — copy data to a fast scratch drive (e.g. NVMe SSD) for processing, then copy results back
- `--keep-work-dir` — don't delete the scratch copy after a successful run
- `--dry-run` — print what would happen without actually doing it
