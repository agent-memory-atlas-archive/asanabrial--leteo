#!/bin/sh
# Does build-install do what openspec/specs/cli.md section 17 says it does?
#
#   sh tools/build-install/check.sh
#
# Both scripts, `scripts/build-install.sh` and `scripts/build-install.ps1` (the
# second under `pwsh`), are run behind stand-ins for the three things they call:
# `rustup`, `cargo`, and the `leteo` that cargo would have installed. Nothing is
# compiled, no store is opened and no agent configuration is read: the stand-in
# `cargo install` drops a stand-in `leteo` into `<root>/bin`, every stand-in
# appends its argv to one log, and the assertions read that log. That is what
# makes the order of the steps, the root a binary lands in, and which agents
# are set up again things a test can say, which a real build cannot.
#
# Every command runs under `env -i`, as in `tools/semantic/check_install.sh`, so
# the only things a script can see are the ones named in `isolated` below.
#
# `pwsh` is needed for the second half, and its absence is a check that could
# not run (exit 2) and not a pass.

set -eu

cd "$(dirname "$0")/../.."
REPO="$(pwd -P)"
command -v pwsh >/dev/null 2>&1 || { echo "build-install check could not run: it needs pwsh" >&2; exit 2; }

# Physical paths throughout: PowerShell reports the working directory without
# symbolic links, and a root made absolute from a relative one has to compare
# equal to the path asserted here.
T="$(cd "$(mktemp -d)" && pwd -P)"
trap 'rm -rf "$T"' EXIT INT TERM
STUB="$T/stub"
mkdir -p "$STUB" "$T/home" "$T/cwd"
LOG="$T/log"

# The preview `leteo uninstall` prints without `--yes`, in the layout the binary
# produces, for the three agents the stand-in knows. Which ones are configured
# is the stand-in's FAKE_CONFIGURED, a list of slugs.
cat > "$STUB/leteo.template" <<'SH'
#!/bin/sh
printf '%s\n' "$0" >> "$FAKE_LOG.exe"
printf 'leteo %s\n' "$*" >> "$FAKE_LOG"
case "${FAKE_FAIL:-}" in
    "$*") echo "stand-in leteo: told to fail" >&2; exit 1 ;;
esac
if [ "${1:-}" = uninstall ]; then
    case "${FAKE_PREVIEW:-normal}" in
        garbage) echo "this is not json"; exit 0 ;;
        empty) printf '{\n  "dry_run": true,\n  "agents": []\n}\n'; exit 0 ;;
        removal) printf '{\n  "dry_run": false,\n  "agents": [\n    {\n      "agent": "claude-code",\n      "was_configured": true\n    }\n  ]\n}\n'; exit 0 ;;
    esac
    if [ "${FAKE_PREVIEW:-normal}" = compact ]; then
        printf '{"dry_run":true,"agents":['
    else
        printf '{\n  "dry_run": true,\n  "agents": [\n'
    fi
    separator=""
    for agent in opencode claude-code codex; do
        configured=false
        case " ${FAKE_CONFIGURED:-} " in *" $agent "*) configured=true ;; esac
        if [ "${FAKE_PREVIEW:-normal}" = compact ]; then
            printf '%s{"agent":"%s","was_configured":%s,"files_changed":1}' "$separator" "$agent" "$configured"
            separator=","
        else
            [ -z "$separator" ] || printf ',\n'
            printf '    {\n      "agent": "%s",\n      "was_configured": %s,\n      "files_changed": 1\n    }' "$agent" "$configured"
            separator=,
        fi
    done
    if [ "${FAKE_PREVIEW:-normal}" = compact ]; then
        printf '],"data_dir":"x"}\n'
    else
        printf '\n  ],\n  "data_dir": "x"\n}\n'
    fi
fi
exit 0
SH

cat > "$STUB/rustup" <<'SH'
#!/bin/sh
printf 'rustup %s\n' "$*" >> "$FAKE_LOG"
case "${FAKE_FAIL:-}" in "$*") echo "stand-in rustup: told to fail" >&2; exit 1 ;; esac
# `rustup run <toolchain> cargo ...` hands over to the cargo on PATH.
if [ "${1:-}" = run ]; then
    shift 2
    exec "$@"
fi
exit 0
SH

cat > "$STUB/cargo" <<'SH'
#!/bin/sh
printf 'cargo %s\n' "$*" >> "$FAKE_LOG"
printf 'cwd %s\n' "$(pwd -P)" >> "$FAKE_LOG"
case "${FAKE_FAIL:-}" in "$*") echo "stand-in cargo: told to fail" >&2; exit 1 ;; esac
if [ "${1:-}" = install ]; then
    root=""
    while [ "$#" -gt 0 ]; do
        [ "$1" = --root ] && root="$2"
        shift
    done
    [ -n "$root" ] || { echo "stand-in cargo: install without --root" >&2; exit 1; }
    [ -z "${FAKE_NO_BINARY:-}" ] || exit 0
    mkdir -p "$root/bin"
    cp "$FAKE_TEMPLATE" "$root/bin/leteo"
    cp "$FAKE_TEMPLATE" "$root/bin/leteo.exe"
    chmod +x "$root/bin/leteo" "$root/bin/leteo.exe"
fi
exit 0
SH
chmod +x "$STUB/rustup" "$STUB/cargo" "$STUB/leteo.template"

failed=0
ran=0
ok() { ran=$((ran + 1)); printf 'ok    %s\n' "$1"; }
bad() { ran=$((ran + 1)); failed=1; printf 'FAIL  %s\n' "$1"; }

# run <runner> <name> [VAR=value...]: runs one script in a fresh log, from the
# `cwd` directory, and leaves its output in $T/out and its status in $STATUS.
STATUS=0
run() {
    runner="$1"; shift
    : > "$LOG"; : > "$LOG.exe"
    case "$runner" in
        sh) script="sh $REPO/scripts/build-install.sh" ;;
        ps1) script="pwsh -NoProfile -NonInteractive -File $REPO/scripts/build-install.ps1" ;;
    esac
    STATUS=0
    # shellcheck disable=SC2086
    (cd "$T/cwd" && env -i PATH="$STUB:$PATH" HOME="$T/home" FAKE_LOG="$LOG" \
        FAKE_TEMPLATE="$STUB/leteo.template" "$@" $script) >"$T/out" 2>&1 || STATUS=$?
}

has() { grep -qF -- "$1" "$LOG"; }
lacks() { ! grep -qF -- "$1" "$LOG"; }
said() { grep -qF -- "$1" "$T/out"; }
last_line_is() { [ "$(tail -n 1 "$LOG")" = "$1" ]; }
# expect <description> <condition...>
expect() {
    description="$1"; shift
    if "$@"; then ok "$description"; else bad "$description"; sed 's/^/        | /' "$T/out" | tail -n 12; fi
}
succeeded() { [ "$STATUS" -eq 0 ]; }
failed_status() { [ "$STATUS" -ne 0 ]; }
no_setup() { ! grep -q '^leteo setup ' "$LOG"; }

for runner in sh ps1; do
    echo "-- $runner: the root a binary lands in"
    R="$T/root-$runner"
    run "$runner" CARGO_INSTALL_ROOT="$R/a" CARGO_HOME="$R/b"
    expect "CARGO_INSTALL_ROOT outranks CARGO_HOME" has "install --root $R/a "
    expect "and the binary there is the one that ran" grep -qF "$R/a/bin/leteo" "$LOG.exe"
    run "$runner" CARGO_HOME="$R/b"
    expect "CARGO_HOME outranks HOME" has "install --root $R/b "
    run "$runner"
    expect "with neither, the root is HOME/.cargo" has "install --root $T/home/.cargo "
    run "$runner" CARGO_INSTALL_ROOT="rel/root"
    expect "a relative root is made absolute from the caller's directory" has "install --root $T/cwd/rel/root "
    expect "the build and the install run in the checkout, not where the script was called from" grep -qx "cwd $REPO" "$LOG"
    expect "the build is locked and in release mode, with the pinned toolchain" has "rustup run 1.97.0 cargo build --release --locked"
    expect "and the install is locked, forced, and of this checkout" has "--path . --locked --force"

    echo "-- $runner: the steps, in order, with the model from this checkout"
    run "$runner" CARGO_INSTALL_ROOT="$R/a" FAKE_CONFIGURED="claude-code"
    expect "the run succeeds" succeeded
    expect "the toolchain is installed first" has "rustup toolchain install 1.97.0 --profile minimal"
    expect "the model comes from the checkout" has "leteo model install --from $REPO/assets/model"
    # shellcheck disable=SC2016
    expect "toolchain, build, install, version, model, setup, doctor in that order" sh -c '
        n=0; for step in "toolchain install" "cargo build" "cargo install" "leteo --version" "leteo model install" "leteo setup" "leteo doctor"; do
            line="$(grep -nF -- "$step" "$1" | head -n 1 | cut -d: -f1)"
            [ -n "$line" ] && [ "$line" -gt "$n" ] || { echo "out of order: $step" >&2; exit 1; }
            n="$line"
        done' sh "$LOG"
    expect "doctor is the last thing run" last_line_is "leteo doctor"
    expect "uninstall is only ever the preview, never --yes" lacks "uninstall --yes"

    echo "-- $runner: which agents are set up again"
    run "$runner" CARGO_INSTALL_ROOT="$R/a" FAKE_CONFIGURED="claude-code codex"
    expect "a configured agent is set up again" has "leteo setup claude-code"
    expect "so is the other configured one" has "leteo setup codex"
    expect "an agent without Leteo is not given any" lacks "leteo setup opencode"
    expect "setup is plain, with no flag an agent might refuse" lacks "leteo setup claude-code -"
    run "$runner" CARGO_INSTALL_ROOT="$R/a" FAKE_CONFIGURED="codex" FAKE_PREVIEW=compact
    expect "a compact reply reads the same: codex is set up" has "leteo setup codex"
    expect "and the others are not" lacks "leteo setup claude-code"
    run "$runner" CARGO_INSTALL_ROOT="$R/a"
    expect "no configured agent is not an error" succeeded
    expect "it says so" said "No agent has Leteo configured"
    expect "and sets up nobody" no_setup
    expect "and still ends with doctor" last_line_is "leteo doctor"

    echo "-- $runner: LETEO_SETUP_AGENTS"
    run "$runner" CARGO_INSTALL_ROOT="$R/a" LETEO_SETUP_AGENTS="opencode  codex" FAKE_CONFIGURED="claude-code"
    expect "an explicit list is set up as given, configured or not" has "leteo setup opencode"
    expect "all of it" has "leteo setup codex"
    expect "and nothing else" lacks "leteo setup claude-code"
    expect "the preview is not asked for" lacks "leteo uninstall"
    run "$runner" CARGO_INSTALL_ROOT="$R/a" LETEO_SETUP_AGENTS="none" FAKE_CONFIGURED="claude-code"
    expect "none sets up nobody" no_setup
    expect "and asks for no preview" lacks "leteo uninstall"
    expect "but doctor still runs" last_line_is "leteo doctor"
    run "$runner" CARGO_INSTALL_ROOT="$R/a" LETEO_SETUP_AGENTS="   " FAKE_CONFIGURED="claude-code"
    expect "blanks only is unset: the preview decides" has "leteo setup claude-code"
    run "$runner" CARGO_INSTALL_ROOT="$R/a" LETEO_SETUP_AGENTS="none codex"
    expect "none beside another word is not none: both are named" has "leteo setup none"
    expect "including the other" has "leteo setup codex"
    run "$runner" CARGO_INSTALL_ROOT="$R/a" LETEO_SETUP_AGENTS="None"
    expect "none is case-sensitive" has "leteo setup None"

    echo "-- $runner: a reply that cannot be trusted stops the run, naming the command"
    run "$runner" CARGO_INSTALL_ROOT="$R/a" FAKE_PREVIEW=removal
    expect "a reply that is not a preview fails" failed_status
    expect "naming leteo uninstall" said "leteo uninstall"
    expect "and sets nobody up" no_setup
    run "$runner" CARGO_INSTALL_ROOT="$R/a" FAKE_PREVIEW=garbage
    expect "an unreadable reply fails" failed_status
    expect "naming leteo uninstall" said "leteo uninstall"
    # shellcheck disable=SC2016
    expect "and is not reported as no agent configured" sh -c '! grep -qF "No agent has Leteo configured" "$1"' sh "$T/out"
    expect "and does not run doctor" lacks "leteo doctor"
    run "$runner" CARGO_INSTALL_ROOT="$R/a" FAKE_PREVIEW=empty
    expect "a reply listing no agents at all fails" failed_status
    expect "naming leteo uninstall" said "leteo uninstall"
    # shellcheck disable=SC2016
    expect "and is not reported as no agent configured" sh -c '! grep -qF "No agent has Leteo configured" "$1"' sh "$T/out"
    run "$runner" CARGO_INSTALL_ROOT="$R/a" FAKE_FAIL="uninstall"
    expect "a preview that exits non-zero fails" failed_status
    expect "naming leteo uninstall" said "leteo uninstall"

    echo "-- $runner: every step that fails stops the run and is named"
    for step in "rustup toolchain install 1.97.0 --profile minimal" \
                "cargo build --release --locked" \
                "leteo --version" \
                "leteo model install --from $REPO/assets/model" \
                "leteo setup claude-code" \
                "leteo doctor"; do
        # The fake matches on the arguments after the program name.
        case "$step" in
            rustup*) program=rustup ;; cargo*) program=cargo ;; *) program=leteo ;;
        esac
        args="${step#"$program" }"
        if [ "$program" = cargo ]; then
            # cargo is reached through `rustup run`, which hands its arguments on.
            args="build --release --locked"
        fi
        run "$runner" CARGO_INSTALL_ROOT="$R/a" FAKE_CONFIGURED="claude-code" FAKE_FAIL="$args"
        expect "failing '$step' exits non-zero" failed_status
        case "$step" in
            "leteo model install"*) named="model install" ;;
            "leteo setup claude-code") named="setup claude-code" ;;
            "leteo --version") named="--version" ;;
            "leteo doctor") named="doctor" ;;
            "cargo build"*) named="cargo build --release --locked" ;;
            *) named="toolchain install 1.97.0" ;;
        esac
        expect "and names it" said "$named"
        if [ "$step" != "leteo doctor" ]; then
            expect "and doctor does not run after a failure" lacks "leteo doctor"
        fi
    done
    run "$runner" CARGO_INSTALL_ROOT="$R/a" FAKE_FAIL="install --root $R/a --path . --locked --force"
    expect "a failing install exits non-zero" failed_status
    # PowerShell wraps a long error message at the terminal width, so only the
    # front of the command is looked for.
    expect "and names it" said "rustup run 1.97.0 cargo install"
    expect "and nothing is run from a binary it did not install" lacks "leteo --version"
    rm -rf "$R/c"
    run "$runner" CARGO_INSTALL_ROOT="$R/c" FAKE_NO_BINARY=1
    expect "an install that leaves no executable fails" failed_status
    expect "and says where it looked" said "$R/c/bin/leteo"
done

if [ "$failed" -ne 0 ]; then
    echo "build-install check FAILED ($ran assertions)"
    exit 1
fi
echo "build-install check passed ($ran assertions)"
