#!/usr/bin/env bash
# Non-Stop Installer — one-liner: curl -fsSL https://raw.githubusercontent.com/acunningham-ship-it/Non-Stop/main/install.sh | bash
set -euo pipefail

REPO="acunningham-ship-it/Non-Stop"
INSTALL_DIR="${HOME}/non-stop"
PYTHON="${PYTHON:-python3}"

echo "  ⏵ Installing Non-Stop..."

# Clone or update
if [ -d "$INSTALL_DIR" ]; then
    echo "  ⏵ Updating existing installation..."
    cd "$INSTALL_DIR" && git pull --ff-only
else
    echo "  ⏵ Cloning from GitHub..."
    git clone "https://github.com/${REPO}.git" "$INSTALL_DIR"
    cd "$INSTALL_DIR"
fi

# Create venv
echo "  ⏵ Setting up virtual environment..."
"$PYTHON" -m venv .venv
source .venv/bin/activate

# Install dependencies
echo "  ⏵ Installing dependencies..."
pip install --quiet --upgrade pip
pip install --quiet -e .

# Create wrapper script
WRAPPER="${HOME}/.local/bin/nonstop"
mkdir -p "${HOME}/.local/bin"

cat > "$WRAPPER" << 'WRAPEOF'
#!/usr/bin/env bash
exec "$HOME/non-stop/.venv/bin/nonstop" "$@"
WRAPEOF
chmod +x "$WRAPPER"

# Add to PATH if not already
SHELL_CONFIG="${HOME}/.$(basename "${SHELL:-bash}")rc"
if ! grep -q '\.local/bin' "$SHELL_CONFIG" 2>/dev/null; then
    echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$SHELL_CONFIG"
    echo "  ⏵ Added ~/.local/bin to PATH in $SHELL_CONFIG"
fi

echo ""
echo "  ✓ Non-Stop installed!"
echo ""
echo "  To start:  nonstop"
echo "  Or:        source ~/.local/bin/nonstop"
echo "  API key:   export OPENROUTER_API_KEY=\"sk-...\""
echo ""