#!/usr/bin/env bash
# setup_deps.sh
# Installs all dependencies including the py-clob-client stack which lives on
# GitHub rather than PyPI.  Run once after cloning.
#
# Usage:  bash setup_deps.sh

set -e

echo "==> Installing base requirements..."
pip install -r requirements.txt

echo ""
echo "==> Installing poly_eip712_structs compatibility shim..."
# py-clob-client needs 'poly_eip712_structs' which isn't on PyPI.
# We install 'eip712-structs' (which IS on PyPI) and create a thin shim package
# that re-exports everything under the expected module name.
TMP=$(mktemp -d)
mkdir -p "$TMP/poly_eip712_structs"
cat > "$TMP/poly_eip712_structs/__init__.py" << 'PYEOF'
from eip712_structs import EIP712Struct, Address, String, Uint, make_domain, Array, Bytes, Boolean, Int
__version__ = "0.0.1"
PYEOF
cat > "$TMP/setup.py" << 'PYEOF'
from setuptools import setup, find_packages
setup(name="poly_eip712_structs", version="0.0.1",
      packages=find_packages(), install_requires=["eip712-structs"])
PYEOF
pip install "$TMP" --no-deps
rm -rf "$TMP"

echo ""
echo "==> Installing py-order-utils from GitHub..."
pip install "git+https://github.com/Polymarket/python-order-utils.git" \
    --no-deps --ignore-requires-python

echo ""
echo "==> Installing py-clob-client from GitHub..."
pip install "git+https://github.com/Polymarket/py-clob-client.git" \
    --ignore-requires-python

echo ""
echo "==> Verifying install..."
python3 -c "
from py_clob_client.client import ClobClient
from py_clob_client.constants import POLYGON
print('  py-clob-client OK  (POLYGON chain_id =', POLYGON, ')')
"

echo ""
echo "Done!  Copy .env.example to .env and fill in your credentials."
