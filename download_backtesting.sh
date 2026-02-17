#!/usr/bin/env bash
set -euo pipefail

REPO_URL="https://github.com/kernc/backtesting.py.git"
TARGET_DIR="backtesting.py"

if [[ -d "$TARGET_DIR/.git" ]]; then
  echo "Le dépôt '$TARGET_DIR' existe déjà."
  exit 0
fi

echo "Téléchargement de $REPO_URL ..."
git clone "$REPO_URL" "$TARGET_DIR"
echo "✅ Dépôt téléchargé dans ./$TARGET_DIR"
