#!/bin/sh
# Builds this checkout and installs the result on macOS or Linux, with the
# search model from the same checkout and every agent pointed at the new binary.
#
# Run from any location:
#
#   <checkout>/scripts/build-install.sh
#
# This is the developer's path. The release installers (`install.sh`) fetch a
# published archive into `~/.local/bin`; this one installs into Cargo's own
# root, so a source build never lands on top of a release install.
#
# Variables, all optional:
#   CARGO_INSTALL_ROOT, CARGO_HOME  where the binary goes, as Cargo reads them
#   LETEO_SETUP_AGENTS              agents to configure, as slugs separated by
#                                   spaces; `none` configures nothing. Unset
#                                   means the agents that already have Leteo
#                                   configured, and no others.

set -eu

# `rust-version` in Cargo.toml is "1.97"; the patch release is pinned here so
# two developers build with the same compiler. 1.97.0 builds this crate.
TOOLCHAIN='1.97.0'

say() { printf '%s\n' "$*"; }
fail() { printf 'error: %s\n' "$*" >&2; exit 1; }

need() {
    command -v "$1" >/dev/null 2>&1 \
        || fail "'$1' is required but is not available on PATH. Install Rust from https://rustup.rs/ and run this script again."
}

need rustup
need cargo

# The checkout, not this script's own directory: the script lives in
# `scripts/` and everything below builds the crate one level up.
REPOSITORY="$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)"

# Cargo's install root, resolved once and absolutely so the directory written
# to is the directory checked afterwards. The fallback is Cargo's own default,
# `$HOME/.cargo`, not `$HOME`. Cargo's `install.root` config key is not read: a
# machine that sets it should set `CARGO_INSTALL_ROOT` as well. A relative root
# is taken from the caller's working directory, before any `cd`.
if [ -n "${CARGO_INSTALL_ROOT:-}" ]; then
    INSTALL_ROOT="$CARGO_INSTALL_ROOT"
elif [ -n "${CARGO_HOME:-}" ]; then
    INSTALL_ROOT="$CARGO_HOME"
elif [ -n "${HOME:-}" ]; then
    INSTALL_ROOT="$HOME/.cargo"
else
    fail "cannot tell where Cargo installs binaries: set HOME, CARGO_HOME or CARGO_INSTALL_ROOT."
fi
case "$INSTALL_ROOT" in
    /*) ;;
    *) INSTALL_ROOT="$PWD/$INSTALL_ROOT" ;;
esac

say "Installing Rust $TOOLCHAIN if needed"
rustup toolchain install "$TOOLCHAIN" --profile minimal \
    || fail "'rustup toolchain install $TOOLCHAIN --profile minimal' failed."

(
    cd "$REPOSITORY"
    say 'Compiling Leteo in release mode'
    rustup run "$TOOLCHAIN" cargo build --release --locked \
        || fail "'rustup run $TOOLCHAIN cargo build --release --locked' failed."

    say 'Installing the compiled binary'
    rustup run "$TOOLCHAIN" cargo install --root "$INSTALL_ROOT" --path . --locked --force \
        || fail "'rustup run $TOOLCHAIN cargo install --root $INSTALL_ROOT --path . --locked --force' failed. Cargo's own output above says why; if the executable was in use, close the agents running Leteo and try again."
)

LETEO="$INSTALL_ROOT/bin/leteo"
[ -f "$LETEO" ] && [ -x "$LETEO" ] \
    || fail "Cargo reported success, but the installed executable was not found at '$LETEO'."

say 'Installing the model and configuring agents'
"$LETEO" --version || fail "'$LETEO --version' failed."

# The model in this checkout, not the one `model install` would download for
# the binary's version tag: an unreleased build has no such tag to match.
"$LETEO" model install --from "$REPOSITORY/assets/model" \
    || fail "'$LETEO model install --from $REPOSITORY/assets/model' failed."

# Which agents get setup run again. `leteo setup` with no agent configures
# nothing off a terminal (it lists the agents) and is a wizard on one, so the
# agents are named. By default only those that already carry Leteo are named: a
# rebuild moves the binary, and what has to follow it is an existing entry, not
# a new one in an agent this developer never set up. The question is put to the
# binary rather than to the agents' files: `leteo uninstall` without `--yes` is
# a preview that changes nothing, and its `was_configured` is the same
# `is_configured` check `setup` itself uses. The `dry_run` guard keeps a future
# change to that default from turning this into a removal.
# Plain `setup <agent>`, with no `--instructions` or `--hooks`: a typed flag is
# refused for an agent that cannot take it (OpenCode has no lifecycle hooks, Pi
# no instruction file), and one refusal would stop the loop. Plain setup writes
# the MCP entry, which is what has to follow the binary to its new location;
# instructions and hooks stay a deliberate `leteo setup <agent> --instructions
# --hooks`.
AGENTS="${LETEO_SETUP_AGENTS:-}"
if [ -z "$AGENTS" ]; then
    PREVIEW="$("$LETEO" uninstall </dev/null)" \
        || fail "'$LETEO uninstall' failed while looking for configured agents."
    printf '%s\n' "$PREVIEW" | grep -q '"dry_run": true' \
        || fail "'$LETEO uninstall' did not report a preview; refusing to read it as a list of agents."
    AGENTS="$(printf '%s\n' "$PREVIEW" | awk '
        /"agent":/ { gsub(/[",]/, "", $2); agent = $2 }
        /"was_configured": true/ { print agent }')"
    if [ -z "$AGENTS" ]; then
        say "No agent has Leteo configured, so none is set up again. Run '$LETEO setup <agent>' to add one."
        AGENTS='none'
    fi
fi
if [ "$AGENTS" != 'none' ]; then
    for agent in $AGENTS; do
        "$LETEO" setup "$agent" </dev/null \
            || fail "'$LETEO setup $agent' failed."
    done
fi

"$LETEO" doctor || fail "'$LETEO doctor' failed."

say "Installation finished: $LETEO"
