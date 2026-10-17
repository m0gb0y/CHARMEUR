#!/usr/bin/env bash
set -euo pipefail

python3 -m unittest discover -s tests -v
node --test tests/admin_image_preview.test.cjs
