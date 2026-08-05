#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
src_dir=$(cd -- "$script_dir/../.." && pwd)

cd "$src_dir"
python -m unittest discover \
  --start-directory tests/fuzz/property \
  --top-level-directory . \
  --pattern 'test_*.py' \
  --verbose
