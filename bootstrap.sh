#!/usr/bin/env bash
# One-command source install for pst-search on macOS / Linux.
#
# Assumes Python 3.10+ and Node 18+ are already installed. If they aren't,
# the script prints the install command for your platform and exits.

set -euo pipefail
cd "$(dirname "$0")"

need() {
  command -v "$1" >/dev/null 2>&1 || { echo "missing: $1"; missing+=("$1"); }
}

missing=()
need python3
need node
need npm

if [ "${#missing[@]}" -gt 0 ]; then
  echo
  echo "Install missing prerequisites first:"
  case "$(uname -s)" in
    Darwin) echo "  brew install python@3.12 node" ;;
    Linux)  echo "  sudo apt install python3 python3-pip python3-tk python3-venv nodejs npm" ;;
    *)      echo "  (Install Python 3.10+ and Node 18+ for your platform.)" ;;
  esac
  exit 1
fi

python3 -c "import tkinter" 2>/dev/null || {
  echo "Tkinter (file picker) not available for this Python."
  case "$(uname -s)" in
    Darwin) echo "  brew install python-tk@3.12   # or use the python.org installer" ;;
    Linux)  echo "  sudo apt install python3-tk" ;;
  esac
  exit 1
}

echo "==> Installing Python package (editable)"
python3 -m pip install --user -e .

echo "==> Installing Node dependencies"
( cd pst_search/node && npm install --no-audit --no-fund )

echo
echo "Done. Start the app with:"
echo "  pstsearch serve"
echo "Or, if pip's user-script dir isn't on PATH:"
echo "  python3 -m pst_search serve"
