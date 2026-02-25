#!/usr/bin/env bash
set -euo pipefail

python -m pip install --upgrade pip
python -m pip install pyinstaller pymodbus pyserial

pyinstaller \
  --clean \
  --onefile \
  --name d3net_rtu_gui \
  d3net_rtu_gui.py

echo "Built executable: dist/d3net_rtu_gui"
