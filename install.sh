#!/usr/bin/env bash
# Install / update / remove the cc_pid CoolerControl plugin.
#
#   sudo ./install.sh              install or update
#   sudo ./install.sh --uninstall  remove (keeps config.json)
#   sudo ./install.sh --purge      remove everything, including config.json
#   --no-restart                   don't restart coolercontrold afterwards
#
# Overrides: PLUGIN_ID (default cc_pid), PLUGIN_ROOT (default /var/lib/coolercontrol/plugins),
#            PLUGIN_USER (user the plugin runs as, default cc-plugin-user)
set -euo pipefail

PLUGIN_ID="${PLUGIN_ID:-cc_pid}"
PLUGIN_ROOT="${PLUGIN_ROOT:-/var/lib/coolercontrol/plugins}"
DEST="$PLUGIN_ROOT/$PLUGIN_ID"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

ACTION=install
RESTART=1
for arg in "$@"; do
    case "$arg" in
        --uninstall) ACTION=uninstall ;;
        --purge)     ACTION=purge ;;
        --no-restart) RESTART=0 ;;
        -h|--help)   sed -n '2,11p' "$0"; exit 0 ;;
        *) echo "Unknown option: $arg" >&2; exit 1 ;;
    esac
done

if [[ $EUID -ne 0 ]]; then
    exec sudo --preserve-env=PLUGIN_ID,PLUGIN_ROOT,PLUGIN_USER "$0" "$@"
fi

restart_daemon() {
    if [[ $RESTART -eq 1 ]] && systemctl list-unit-files coolercontrold.service &>/dev/null; then
        echo "Restarting coolercontrold..."
        systemctl restart coolercontrold
    else
        echo "Skipping restart. Run: sudo systemctl restart coolercontrold"
    fi
}

if [[ $ACTION != install ]]; then
    if [[ ! -d $DEST ]]; then echo "Nothing to remove at $DEST"; exit 0; fi
    if [[ $ACTION == purge ]]; then
        rm -rf "$DEST"
        rm -rf /etc/cc_pid
    else
        # keep the user's config.json and token, remove everything else
        find "$DEST" -mindepth 1 -maxdepth 1 ! -name config.json ! -name token -exec rm -rf {} +
    fi
    echo "Removed cc_pid from $DEST"
    restart_daemon
    exit 0
fi

# --- install -----------------------------------------------------------
if [[ ! -d $PLUGIN_ROOT ]]; then
    echo "Error: $PLUGIN_ROOT not found. Is CoolerControl installed?" >&2
    exit 1
fi
if [[ ! -f $SRC/manifest.toml ]]; then
    echo "Error: manifest.toml is missing from the repo." >&2
    exit 1
fi

# Python dependency (system Python, as the plugin runs under coolercontrold)
if ! python3 -c "import requests" 2>/dev/null; then
    echo "Installing python3-requests..."
    if   command -v dnf     &>/dev/null; then dnf install -y python3-requests
    elif command -v apt-get &>/dev/null; then apt-get install -y python3-requests
    elif command -v pacman  &>/dev/null; then pacman -S --noconfirm python-requests
    else echo "Install the Python 'requests' package manually." >&2; exit 1
    fi
fi

install -d -m 755 "$DEST"
install -m 755 "$SRC/cc_pid.py"     "$DEST/cc_pid.py"
install -m 644 "$SRC/models.py"     "$DEST/models.py"
install -d -m 755 "$DEST/ui"
install -m 644 "$SRC/ui/index.html" "$DEST/ui/index.html"
rm -f "$DEST/index.html"   # old flat layout
install -m 644 "$SRC/manifest.toml" "$DEST/manifest.toml"

# Never overwrite an existing config on update
if [[ -f $DEST/config.json ]]; then
    echo "Existing config.json kept."
else
    install -m 644 "$SRC/config.empty.json" "$DEST/config.json"
    echo "Created empty config.json (add controls in the plugin UI)."
fi

PLUGIN_USER="${PLUGIN_USER:-cc-plugin-user}"
PLUGIN_GROUP="$(id -gn "$PLUGIN_USER" 2>/dev/null || echo root)"

# API token lives outside the plugin dir: coolercontrold resets ownership of files in there
TOKEN_DIR=/etc/cc_pid
TOKEN_FILE="$TOKEN_DIR/token"
install -d -m 750 -o root -g "$PLUGIN_GROUP" "$TOKEN_DIR"
if [[ ! -e $TOKEN_FILE ]]; then
    if [[ -s $DEST/token ]]; then            # migrate from the old location
        install -m 640 -o root -g "$PLUGIN_GROUP" "$DEST/token" "$TOKEN_FILE"
    else
        (umask 077; : > "$TOKEN_FILE")
    fi
    rm -f "$DEST/token"
    echo "Created $TOKEN_FILE"
fi
chown root:"$PLUGIN_GROUP" "$TOKEN_FILE"
chmod 640 "$TOKEN_FILE"
if [[ ! -s $TOKEN_FILE ]]; then
    echo "NOTE: paste your CoolerControl access token into $TOKEN_FILE"
    echo "      (e.g. sudo nano $TOKEN_FILE), then restart the plugin."
fi

# Ownership: the plugin dir, ui/ and manifest.toml stay root-owned; the files below belong to the plugin user
if id "$PLUGIN_USER" &>/dev/null; then
    chown "$PLUGIN_USER:" "$DEST/ui/index.html" \
        "$DEST/cc_pid.py" "$DEST/models.py" "$DEST/config.json"
    chown root:root "$DEST/manifest.toml"
else
    echo "WARNING: user '$PLUGIN_USER' not found; files left root-owned." >&2
    echo "         Re-run with PLUGIN_USER=<user> if the plugin runs as someone else." >&2
fi

# Fix SELinux contexts on Fedora
if command -v restorecon &>/dev/null; then
    restorecon -R "$DEST" || true
fi

echo "Installed cc_pid to $DEST"
restart_daemon
