@echo off
REM =============================================================================
REM  setup_env.bat  (Windows)
REM  Creates the intan_proc conda environment from environment.yml.
REM
REM  Run once from any terminal:
REM      setup_env.bat
REM
REM  After setup, activate with:
REM      conda activate intan_proc
REM =============================================================================

where conda >nul 2>&1
if errorlevel 1 (
    echo ERROR: conda not found on PATH.
    echo Please run from an Anaconda Prompt or add conda to PATH.
    exit /b 1
)

echo.
echo Creating / updating intan_proc environment from environment.yml ...
conda env create -f "%~dp0environment.yml"
if errorlevel 1 (
    echo Environment already exists - updating instead...
    conda env update -f "%~dp0environment.yml" --prune
)

echo.
echo Done.  Activate with:  conda activate intan_proc
