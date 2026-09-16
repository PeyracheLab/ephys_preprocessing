#!/usr/bin/env bash
# =============================================================================
#  setup_env.sh  (Linux / macOS)
#  Creates the intan_proc conda environment from environment.yml.
#
#  Run once:
#      bash setup_env.sh
#
#  After setup, activate with:
#      conda activate intan_proc
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if ! command -v conda &>/dev/null; then
    echo "ERROR: conda not found on PATH."
    echo "Please install Miniconda/Anaconda and initialise your shell with 'conda init'."
    exit 1
fi

echo
echo "Creating / updating intan_proc environment from environment.yml ..."
conda env create -f "$SCRIPT_DIR/environment.yml" \
    || conda env update -f "$SCRIPT_DIR/environment.yml" --prune

echo
echo "Done.  Activate with:  conda activate intan_proc"
