# nwb-builder

A small, GUI-free replacement for [nwbmatic](https://github.com/pynapple-org/nwbmatic) (deprecated)
for one specific pipeline: Intan/Neurosuite ephys (`.xml`, `.clu`/`.res`, `Epoch_TS.csv`) +
Optitrack tracking (per-epoch `.csv` + `analogin.dat` TTL sync) -> a single `.nwb` file per
session, written with the same NWB layout nwbmatic used so it reads back as
[pynapple](https://github.com/pynapple-org/pynapple) objects (`nap.load_file(...)`).

## What it expects in a session folder

One folder per session (e.g. `B6312-260911`), named the same as the files inside it:

- `<basename>.xml` — Neuroscope/NDManager params: channel count, sampling rate, shank/channel groups
- `Epoch_TS.csv` — one `start_seconds,end_seconds` line per epoch, in the recording's global clock
- `<basename>.clu.N` / `<basename>.res.N` — curated spike times per shank `N`
- `<basename>_<epoch_index>.csv` — Optitrack export for that epoch (x, y, z, rx, ry, rz), optional
- `<basename>_<epoch_index>_analogin.dat` — single-channel TTL sync trace for that epoch, optional

Position is only written for epochs where both the tracking csv and the analogin TTL file are
present. TTL rising edges are matched 1:1 to Optitrack frames (min length of the two, like
nwbmatic did) and offset by the epoch's start time so everything lands on the same global clock as
the spikes and epochs.

## Setup

```powershell
cd nwb-builder
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
```

## Usage

The `.nwb` is written into the session folder itself, named `<basename>.nwb`, unless `-o/--output`
is given. Always sanity-check with `--dry-run` first — it prints channel counts, epoch boundaries,
TTL/frame-count sync diagnostics, and unit counts per shank without writing anything.

```powershell
.\.venv\Scripts\python.exe -m nwb_builder "<path to session folder>" --dry-run
.\.venv\Scripts\python.exe -m nwb_builder "<path to session folder>"
```

Or, after `pip install -e .`, the `nwb-build` console script is also on PATH inside the venv:

```powershell
.\.venv\Scripts\nwb-build.exe "<path to session folder>"
```

### For B6312 on Hypernova (all three recording days)

```powershell
.\.venv\Scripts\python.exe -m nwb_builder "\\HypernovaPeyra\Hypernova2_Data\Adel\B6312\B6312_260911\B6312-260911"
.\.venv\Scripts\python.exe -m nwb_builder "\\HypernovaPeyra\Hypernova2_Data\Adel\B6312\B6312_260912\B6312-260912"
.\.venv\Scripts\python.exe -m nwb_builder "\\HypernovaPeyra\Hypernova2_Data\Adel\B6312\B6312_260913\B6312-260913"
```

Each writes e.g. `B6312-260911.nwb` next to the rest of that day's data.

### Useful flags

- `--force` — overwrite an existing `.nwb`
- `--location "CA1"` or `--location "CA1,CA1,CA3,CA3"` — brain region, one value for all shanks or
  one per shank (shank count comes from the `.xml`)
- `--epoch-labels sleep1,wake,sleep2` — name the epochs instead of `epoch0,epoch1,...`
- `--lab`, `--institution`, `--experimenter`, `--species`, `--sex`, `--genotype`,
  `--subject-id` — session/subject metadata (defaults: lab="Peyrache Lab",
  institution="McGill University", species="Mus musculus", subject id parsed from the folder name)
- `--session-start-time 2026-09-11T14:17:34` — override the auto-detected session start time
  (by default it's parsed from the Optitrack "Capture Start Time" header of epoch 0, falling back
  to the date encoded in the folder name)

## Reading the result back

```python
import pynapple as nap
data = nap.load_file("B6312-260911.nwb")
data["units"]                   # TsGroup of spike times, with `group` (shank) and `location` info
data["x"], data["y"], data["z"]         # Tsd position, meters
data["rx"], data["ry"], data["rz"]      # Tsd rotation, radians in [0, 2*pi)
data["epochs"]                  # IntervalSet of the recording epochs
data["position_time_support"]   # IntervalSet of when tracking was actually valid per epoch
```

## Package layout

- `xml_params.py` — parse `.xml` for channel count / sampling rate / shank-to-channel map
- `epochs.py` — parse `Epoch_TS.csv`
- `optitrack.py` — parse the Optitrack tracking csv (and its header metadata)
- `ttl.py` — detect TTL rising edges in `analogin.dat`
- `spikes.py` — parse `.clu`/`.res` into per-unit spike times (drops noise/MUA clusters 0 and 1)
- `build_nwb.py` — orchestrates all of the above into one `NWBFile` and writes it
- `cli.py` — argparse CLI (`nwb-build`)
