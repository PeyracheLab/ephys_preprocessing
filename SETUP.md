# Setup

One-time environment setup for the Intan pre-processing pipeline. Works on both macOS/Linux and Windows.

1. **Get the repo.** Easiest for non-technical users — no git required:
   On GitHub, go to `github.com/PeyracheLab/ephys_preprocessing` → green **Code** button → **Download ZIP** → unzip it (anywhere is fine, e.g. `Documents`).

   *(Alternative for git users: `git clone https://github.com/PeyracheLab/ephys_preprocessing.git`)*

2. **Install uv.**
   - macOS/Linux: open a terminal, run:
     ```
     curl -LsSf https://astral.sh/uv/install.sh | sh
     ```
   - Windows: open PowerShell, run:
     ```
     powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
     ```
   Then close and reopen your terminal (so `uv` is on `PATH`).

3. **cd into the repo folder** — the one that directly contains `requirements.txt` and `Toolbox/` (i.e. `ephys_preprocessing`, wherever you unzipped/cloned it):
   ```
   cd path/to/ephys_preprocessing
   ```

4. **Pick your CUDA build.** Open `requirements.txt` in a text editor and follow the instructions at the top: run `nvidia-smi`, find the `CUDA Version: X.Y` line, uncomment the matching torch block (or the CPU-only block if you have no NVIDIA GPU). Save the file.

5. **Create the environment.** It must be named `pp_env` and created right here at the repo root — the pipeline auto-detects it by this name and location:
   ```
   uv venv pp_env --python 3.12
   ```

6. **Activate it:**
   - Mac/Linux: `source pp_env/bin/activate` (prompt shows `(pp_env)`)
   - Windows: `pp_env\Scripts\activate`

7. **Install packages:**
   ```
   uv pip install -r requirements.txt
   ```
