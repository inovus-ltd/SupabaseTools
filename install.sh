#!/usr/bin/env bash
# ============================================================
#  SupabaseTools Installer (macOS / Linux)
#  Downloads the latest release binaries from GitHub and
#  installs them to /usr/local/bin (requires sudo).
#
#  Usage (one-liner):
#    curl -fsSL https://raw.githubusercontent.com/inovus-ltd/SupabaseTools/master/install.sh | sudo bash
#
#  Or if you have the file locally:
#    sudo bash install.sh
# ============================================================

set -e

REPO="inovus-ltd/SupabaseTools"
INSTALL_DIR="/usr/local/bin"

TOOLS=(
    "supabase-functions-backup"
    "supabase-storage-copy"
    "supabase-auth-copy"
    "supabase-secrets-manager"
    "supabase-database-compare"
    "supabase-database-sync"
)

# -- Colour helpers -----------------------------------------------------------
GREEN="\033[0;32m"
CYAN="\033[0;36m"
RED="\033[0;31m"
YELLOW="\033[0;33m"
RESET="\033[0m"

echo ""
echo -e " ${CYAN}SupabaseTools Installer${RESET}"
echo -e " ${CYAN}─────────────────────────────────────────${RESET}"

# -- Detect platform ----------------------------------------------------------
OS="$(uname -s)"
case "$OS" in
    Darwin) PLATFORM="macos" ;;
    Linux)  PLATFORM="linux" ;;
    *)
        echo -e " ${RED}ERROR: Unsupported OS: $OS${RESET}"
        exit 1
        ;;
esac
echo " Platform: $PLATFORM"

# -- Check for sudo -----------------------------------------------------------
if [ "$EUID" -ne 0 ]; then
    echo ""
    echo -e " ${RED}ERROR: This installer must be run with sudo.${RESET}"
    echo -e " ${YELLOW}       Re-run as: sudo bash install.sh${RESET}"
    echo -e " ${YELLOW}       Or use the one-liner: curl -fsSL https://raw.githubusercontent.com/${REPO}/master/install.sh | sudo bash${RESET}"
    exit 1
fi

# -- Resolve latest release tag -----------------------------------------------
echo ""
echo -n " Fetching latest release info..."
API_URL="https://api.github.com/repos/${REPO}/releases/latest"

if command -v curl &>/dev/null; then
    TAG=$(curl -fsSL -H "User-Agent: SupabaseTools-Installer" "$API_URL" | grep '"tag_name"' | sed 's/.*"tag_name": *"\([^"]*\)".*/\1/')
elif command -v wget &>/dev/null; then
    TAG=$(wget -qO- --header="User-Agent: SupabaseTools-Installer" "$API_URL" | grep '"tag_name"' | sed 's/.*"tag_name": *"\([^"]*\)".*/\1/')
else
    echo ""
    echo -e " ${RED}ERROR: Neither curl nor wget is available.${RESET}"
    exit 1
fi

if [ -z "$TAG" ]; then
    echo ""
    echo -e " ${RED}ERROR: Could not determine latest release tag.${RESET}"
    exit 1
fi
echo -e " ${GREEN}${TAG}${RESET}"

# -- Download and install each tool -------------------------------------------
echo " Installing to: $INSTALL_DIR"
echo ""

for TOOL in "${TOOLS[@]}"; do
    FILENAME="${TOOL}-${PLATFORM}"
    URL="https://github.com/${REPO}/releases/download/${TAG}/${FILENAME}"
    DEST="${INSTALL_DIR}/${TOOL}"

    printf " Downloading %s..." "$TOOL"
    if command -v curl &>/dev/null; then
        curl -fsSL "$URL" -o "$DEST"
    else
        wget -qO "$DEST" "$URL"
    fi
    chmod +x "$DEST"
    echo -e " ${GREEN}done${RESET}"
done

# -- Verify -------------------------------------------------------------------
echo ""
echo -e " ${CYAN}Installed tools:${RESET}"
for TOOL in "${TOOLS[@]}"; do
    if command -v "$TOOL" &>/dev/null; then
        echo -e "   ${GREEN}${TOOL}${RESET}"
    else
        echo -e "   ${RED}${TOOL}  (not found in PATH — may need a new shell)${RESET}"
    fi
done

echo ""
echo -e " ${CYAN}Installation complete! Run:${RESET}"
echo "   supabase-functions-backup list --project-ref <ref> --token <token>"
echo "   supabase-storage-copy list --project-ref <ref> --token <token> --service-key <key>"
echo "   supabase-auth-copy list --project-ref <ref> --token <token>"
echo "   supabase-secrets-manager list --project-ref <ref> --token <token>"
echo "   supabase-database-compare compare --source-ref <source> --target-ref <target> --token <token>"
echo "   supabase-database-sync plan --source-ref <source> --target-ref <target> --token <token>"
echo ""
