#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WEB_DIR="$ROOT_DIR/web-components/ProfileMemorySkillsEditor"
RESOURCES_DIR="$ROOT_DIR/client/Sources/Resources/ProfileMemorySkillsEditorWebAssets"

cd "$WEB_DIR"

# Self-bootstrap dependencies so a clean checkout / CI runner builds without a
# manual step (node_modules is git-ignored). Mirrors build-agent-task-assets.sh.
if [ ! -d "node_modules" ]; then
    echo "📦 Installing npm dependencies (no node_modules present in $WEB_DIR)..."
    npm install
fi

npm run build

rm -rf "$RESOURCES_DIR"
mkdir -p "$RESOURCES_DIR"
cp -R "$WEB_DIR/dist/." "$RESOURCES_DIR/"
