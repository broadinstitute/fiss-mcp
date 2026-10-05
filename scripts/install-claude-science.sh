#!/usr/bin/env bash
#
# install-claude-science.sh
#
# Install fiss-mcp as a Claude Science "Local command" connector on macOS.
#
# Claude Science runs local connectors in a macOS sandbox that cannot execute
# or read anything under $HOME, cannot write anywhere except /tmp, and routes
# all network traffic through a proxy with a domain allowlist. This script
# installs everything into a directory outside your home (default
# /opt/fiss-mcp) using a Homebrew Python, and prints the exact connector
# settings and allowed domains to paste into Claude Science at the end.
#
# Usage:
#   ./scripts/install-claude-science.sh [options]
#
# Options:
#   --allow-writes         Enable write tools (submit_workflow, upload_entities, ...)
#
# The generated launcher passes --gcs-backend xml, since Claude Science blocks
# storage.googleapis.com and only per-bucket hostnames are reachable.
#   --source DIR           Install from a local checkout instead of cloning from GitHub
#   --install-dir DIR      Install location (default: /opt/fiss-mcp; must NOT be under $HOME)
#   --python PATH          Python interpreter to use (default: autodetect Homebrew python3)
#   --credentials PATH     Credentials JSON to copy (default: your gcloud ADC file)
#   --gcloud-dir DIR       Directory containing the gcloud binary (default: autodetect)
#   --skip-smoke-test      Don't call Terra at the end
#   -h, --help             Show this help
#
set -euo pipefail

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
INSTALL_DIR="/opt/fiss-mcp"
REPO_URL="https://github.com/broadinstitute/fiss-mcp"
SOURCE_DIR=""
PYTHON=""
CREDENTIALS=""
GCLOUD_DIR=""
ALLOW_WRITES=0
SMOKE_TEST=1

# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------
TOTAL_STEPS=8
STEP=0

if [[ -t 1 ]]; then
  BOLD=$'\033[1m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; RED=$'\033[31m'; RESET=$'\033[0m'
else
  BOLD=""; GREEN=""; YELLOW=""; RED=""; RESET=""
fi

step() { STEP=$((STEP + 1)); printf '\n%s[%d/%d] %s%s\n' "$BOLD" "$STEP" "$TOTAL_STEPS" "$*" "$RESET"; }
ok()   { printf '  %s✓%s %s\n' "$GREEN" "$RESET" "$*"; }
info() { printf '  · %s\n' "$*"; }
warn() { printf '  %s!%s %s\n' "$YELLOW" "$RESET" "$*"; }
die()  { printf '\n%s✗ %s%s\n' "$RED" "$*" "$RESET" >&2; exit 1; }

usage() { sed -n '2,/^set -euo/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'; exit 0; }

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --allow-writes)    ALLOW_WRITES=1; shift ;;
    --source)          SOURCE_DIR="$2"; shift 2 ;;
    --install-dir)     INSTALL_DIR="$2"; shift 2 ;;
    --python)          PYTHON="$2"; shift 2 ;;
    --credentials)     CREDENTIALS="$2"; shift 2 ;;
    --gcloud-dir)      GCLOUD_DIR="$2"; shift 2 ;;
    --skip-smoke-test) SMOKE_TEST=0; shift ;;
    -h|--help)         usage ;;
    *) die "Unknown option: $1 (see --help)" ;;
  esac
done

under_home() { case "$1" in "$HOME"/*|"$HOME") return 0 ;; *) return 1 ;; esac; }

printf '%sfiss-mcp → Claude Science installer%s\n' "$BOLD" "$RESET"
info "install dir : $INSTALL_DIR"
info "mode        : $([[ $ALLOW_WRITES -eq 1 ]] && echo 'write-enabled' || echo 'read-only')"

# ---------------------------------------------------------------------------
step "Preflight checks"
# ---------------------------------------------------------------------------
[[ "$(uname -s)" == "Darwin" ]] || die "This installer targets macOS (Claude Science's sandbox is macOS-specific)."
command -v brew >/dev/null 2>&1 || die "Homebrew not found. Install it from https://brew.sh first."
command -v git  >/dev/null 2>&1 || die "git not found."
under_home "$INSTALL_DIR" && die "Install dir $INSTALL_DIR is under your home directory; the sandbox cannot read it. Choose e.g. /opt/fiss-mcp."
ok "macOS, Homebrew, git present; install dir is outside \$HOME"

# ---------------------------------------------------------------------------
step "Locate a Python interpreter outside \$HOME"
# ---------------------------------------------------------------------------
if [[ -z "$PYTHON" ]]; then
  for candidate in /opt/homebrew/bin/python3.12 /usr/local/bin/python3.12 \
                   /opt/homebrew/bin/python3.13 /usr/local/bin/python3.13 \
                   /opt/homebrew/bin/python3 /usr/local/bin/python3; do
    if [[ -x "$candidate" ]]; then PYTHON="$candidate"; break; fi
  done
fi
if [[ -z "$PYTHON" ]]; then
  warn "No Homebrew Python found; installing python@3.12 (this can take a minute)"
  brew install python@3.12
  PYTHON="$(brew --prefix)/bin/python3.12"
fi
[[ -x "$PYTHON" ]] || die "Python interpreter not executable: $PYTHON"
REAL_PYTHON="$(cd "$(dirname "$PYTHON")" && python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$PYTHON" 2>/dev/null || readlink -f "$PYTHON")"
under_home "$REAL_PYTHON" && die "$PYTHON resolves to $REAL_PYTHON, which is under \$HOME; the sandbox cannot execute it. Use --python /opt/homebrew/bin/python3.12."
PYVER="$("$PYTHON" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
ok "using $PYTHON (Python $PYVER, resolves to $REAL_PYTHON)"

# ---------------------------------------------------------------------------
step "Locate gcloud (FISS requires it on PATH)"
# ---------------------------------------------------------------------------
if [[ -z "$GCLOUD_DIR" ]]; then
  if command -v gcloud >/dev/null 2>&1; then
    GCLOUD_DIR="$(dirname "$(command -v gcloud)")"
  elif [[ -x "$(brew --prefix)/share/google-cloud-sdk/bin/gcloud" ]]; then
    GCLOUD_DIR="$(brew --prefix)/share/google-cloud-sdk/bin"
  else
    die "gcloud not found. Install with:  brew install --cask google-cloud-sdk  (then re-run), or pass --gcloud-dir."
  fi
fi
[[ -x "$GCLOUD_DIR/gcloud" ]] || die "No gcloud binary in $GCLOUD_DIR"
if under_home "$GCLOUD_DIR"; then
  warn "gcloud is under \$HOME ($GCLOUD_DIR). FISS only checks the file exists, which worked in testing;"
  warn "if the connector fails on PATH/gcloud, run: brew install --cask google-cloud-sdk  and re-run with"
  warn "  --gcloud-dir $(brew --prefix)/share/google-cloud-sdk/bin"
fi
ok "gcloud at $GCLOUD_DIR/gcloud"

# ---------------------------------------------------------------------------
step "Create $INSTALL_DIR"
# ---------------------------------------------------------------------------
if [[ ! -d "$INSTALL_DIR" ]]; then
  info "sudo is needed once to create $INSTALL_DIR and hand it to you"
  sudo mkdir -p "$INSTALL_DIR"
  sudo chown "$(id -un)" "$INSTALL_DIR"
fi
[[ -w "$INSTALL_DIR" ]] || die "$INSTALL_DIR exists but is not writable by $(id -un)"
ok "$INSTALL_DIR ready"

# ---------------------------------------------------------------------------
step "Install the fiss-mcp source"
# ---------------------------------------------------------------------------
REPO_DIR="$INSTALL_DIR/repo"
if [[ -n "$SOURCE_DIR" ]]; then
  [[ -f "$SOURCE_DIR/src/terra_mcp/server.py" ]] || die "--source $SOURCE_DIR doesn't look like a fiss-mcp checkout"
  info "copying from $SOURCE_DIR (excluding venvs and caches)"
  mkdir -p "$REPO_DIR"
  # --progress, not --info=progress2: macOS ships rsync 2.6.9, which predates --info
  rsync -a --delete --progress \
    --exclude 'venv' --exclude '.venv' --exclude '__pycache__' --exclude '*.egg-info' \
    "$SOURCE_DIR/" "$REPO_DIR/"
elif [[ -d "$REPO_DIR/.git" ]]; then
  info "existing clone found; pulling latest"
  git -C "$REPO_DIR" pull --ff-only --progress
else
  info "cloning $REPO_URL"
  git clone --progress "$REPO_URL" "$REPO_DIR"
fi
ok "source at $REPO_DIR"

# ---------------------------------------------------------------------------
step "Create venv and install dependencies"
# ---------------------------------------------------------------------------
VENV="$INSTALL_DIR/venv"
if [[ ! -x "$VENV/bin/python3" ]]; then
  info "creating venv"
  "$PYTHON" -m venv "$VENV"
fi
info "installing fiss-mcp into venv (pip shows its own progress)"
"$VENV/bin/pip" install --upgrade pip -q
"$VENV/bin/pip" install -e "$REPO_DIR"
"$VENV/bin/python3" -c "import fastmcp, firecloud, google.cloud.storage" \
  || die "dependency import failed inside $VENV"
ok "venv at $VENV"

# ---------------------------------------------------------------------------
step "Install Google credentials"
# ---------------------------------------------------------------------------
ADC_DEST="$INSTALL_DIR/adc.json"
if [[ -z "$CREDENTIALS" ]]; then
  CREDENTIALS="${CLOUDSDK_CONFIG:-$HOME/.config/gcloud}/application_default_credentials.json"
  if [[ ! -f "$CREDENTIALS" ]]; then
    warn "No Application Default Credentials found; running 'gcloud auth application-default login'"
    "$GCLOUD_DIR/gcloud" auth application-default login
  fi
fi
[[ -f "$CREDENTIALS" ]] || die "Credentials file not found: $CREDENTIALS"
cp "$CREDENTIALS" "$ADC_DEST"
chmod 600 "$ADC_DEST"
ok "copied to $ADC_DEST (mode 600)"
warn "This file contains a long-lived token for your Google account. Treat it like a password."

# ---------------------------------------------------------------------------
step "Write launcher and run smoke test"
# ---------------------------------------------------------------------------
RUN_SH="$INSTALL_DIR/run.sh"
WRITE_FLAG=""
[[ $ALLOW_WRITES -eq 1 ]] && WRITE_FLAG=" --allow-writes"
cat > "$RUN_SH" <<EOF
#!/bin/sh
# Launcher for the Claude Science connector. Generated by install-claude-science.sh.
# The sandbox can only write to the system temp dir, so stderr goes to /tmp.
LOG=/tmp/fiss-mcp-stderr.log
echo "=== \$(date) ===" >> "\$LOG" 2>/dev/null || LOG=/dev/null
exec "$VENV/bin/python3" "$REPO_DIR/src/terra_mcp/server.py" --gcs-backend xml "\$@"$WRITE_FLAG 2>>"\$LOG"
EOF
chmod +x "$RUN_SH"
ok "launcher at $RUN_SH"

CONNECTOR_PATH="$GCLOUD_DIR:$(brew --prefix)/bin:/usr/local/bin:/usr/bin:/bin"

if [[ $SMOKE_TEST -eq 1 ]]; then
  info "calling Terra list_workspaces with the sandbox-like environment..."
  # Must not abort the installer: under `set -e` a failed command substitution
  # would skip the warning branch below and the connector settings at the end.
  STATUS="$(env -i HOME="$INSTALL_DIR" \
      GOOGLE_APPLICATION_CREDENTIALS="$ADC_DEST" \
      PATH="$CONNECTOR_PATH" \
      "$VENV/bin/python3" -c 'from firecloud import api as fapi; print(fapi.list_workspaces().status_code)' 2>&1 | tail -1)" || true
  [[ -n "$STATUS" ]] || STATUS="(smoke test produced no output)"
  if [[ "$STATUS" == "200" ]]; then
    ok "Terra responded 200 — credentials and PATH are good"
  else
    warn "Terra smoke test did not return 200 (got: $STATUS)."
    warn "Check credentials with: $GCLOUD_DIR/gcloud auth application-default login"
  fi
else
  info "smoke test skipped"
fi

# ---------------------------------------------------------------------------
# Final instructions
# ---------------------------------------------------------------------------
cat <<EOF

${BOLD}${GREEN}Done.${RESET} Now add the connector in Claude Science:

  ${BOLD}Connectors → Add connector → Local command${RESET}

  Name:
    terra

  Command:
    $RUN_SH

  Environment variables (paste these three lines):
    HOME=$INSTALL_DIR
    GOOGLE_APPLICATION_CREDENTIALS=$ADC_DEST
    PATH=$CONNECTOR_PATH

  Optional, and only used by --gcs-backend json:
    GOOGLE_CLOUD_PROJECT=<a-real-project-id>

  Description (optional):
    Terra.bio workspaces, data tables, submissions, logs$([[ $ALLOW_WRITES -eq 1 ]] && echo ' (write-enabled)' || echo ' (read-only)')

  ${BOLD}Allowed domains${RESET} (connector setting; paste the list):
    oauth2.googleapis.com
    api.firecloud.org
    batch.googleapis.com
    www.googleapis.com

  ${BOLD}Plus one line per bucket you need to read${RESET}, e.g.:
    fc-<workspace-bucket-uuid>.storage.googleapis.com
  (the bucket name is the bucketName field from get_workspace_metadata;
   wildcards such as *.storage.googleapis.com are rejected, so list each
   bucket by name)

Notes:
  - Do NOT set TMPDIR.
  - storage.googleapis.com itself is always blocked by Claude Science. The
    launcher therefore passes --gcs-backend xml, which reaches buckets through
    their own hostnames instead. Without the per-bucket domains above, the GCS
    tools and get_workflow_logs(fetch_content=True) will fail with
    "Could not reach fc-....storage.googleapis.com through the sandbox proxy".
  - download_gcs_file can only write under /tmp in the sandbox.
  - Claude Science keeps the server process alive; after changing anything,
    restart it:  pkill -f terra_mcp/server.py
  - Server logs: tail -n 60 /tmp/fiss-mcp-stderr.log
  - To update later, re-run this script; it pulls the repo and re-copies credentials.
EOF
