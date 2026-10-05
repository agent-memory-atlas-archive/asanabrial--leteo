#!/bin/sh
# Does an installed Leteo find its model, and does uninstalling take it away?
#
#   sh tools/semantic/check_install.sh [path-to-release-leteo]
#
# The model is a file beside the binary and not inside it, so nothing fails if
# the release stops carrying it, or an installer puts it somewhere the binary
# does not look: `doctor` says the stage is off and search carries on by words.
# This builds an archive laid out the way `release.yml` packs one, runs
# `scripts/install.sh` against it over file://, asks the installed binary's
# `doctor`, and then removes Leteo three ways -- `leteo uninstall --yes`,
# `uninstall.sh` with the binary there, and `uninstall.sh` with the binary gone --
# and asserts that no model file or directory it created is left, and that
# `share/` is.
#
# Unix only, by `install.sh`'s own limit. The npm wrapper and `install.ps1` are
# not covered here.
#
# Nothing touches the real home or store: HOME, the data directory and every
# variable `leteo setup` reads for an agent's configuration are pointed into one
# temporary directory, which is removed on the way out.

set -eu

cd "$(dirname "$0")/../.."
BINARY="${1:-target/release/leteo}"
[ -f "$BINARY" ] || { echo "install check could not run: $BINARY is not a file" >&2; exit 2; }
BINARY="$(cd "$(dirname "$BINARY")" && pwd)/$(basename "$BINARY")"
REPO="$(pwd)"

ROOT="$(mktemp -d)"
trap 'rm -rf "$ROOT"' EXIT INT TERM

VERSION="v0.0.0-install-check"
# The names install.sh derives from the machine; it has no way to be asked.
case "$(uname -s)" in
    Linux)  os="unknown-linux-gnu" ;;
    Darwin) os="apple-darwin" ;;
    *) echo "install check could not run: no archive layout for $(uname -s)" >&2; exit 2 ;;
esac
case "$(uname -m)" in
    x86_64|amd64)  arch="x86_64" ;;
    arm64|aarch64) arch="aarch64" ;;
    *) echo "install check could not run: no archive layout for $(uname -m)" >&2; exit 2 ;;
esac
PACKAGE="leteo-$VERSION-$arch-$os"

# The staging steps of release.yml, for the files this concerns.
mkdir -p "$ROOT/dist/$PACKAGE"
cp "$BINARY" "$ROOT/dist/$PACKAGE/leteo"
cp scripts/uninstall.sh "$ROOT/dist/$PACKAGE/"
cp -R assets/model "$ROOT/dist/$PACKAGE/model"
cp -R LICENSES "$ROOT/dist/$PACKAGE/LICENSES"
tar -C "$ROOT/dist" -czf "$ROOT/dist/$PACKAGE.tar.gz" "$PACKAGE"
rm -rf "$ROOT/dist/$PACKAGE"
if command -v sha256sum >/dev/null 2>&1; then
    (cd "$ROOT/dist" && sha256sum "$PACKAGE.tar.gz" > SHA256SUMS)
else
    (cd "$ROOT/dist" && shasum -a 256 "$PACKAGE.tar.gz" > SHA256SUMS)
fi

failed=0
check() {
    # check <description> <command...>
    description="$1"; shift
    if "$@"; then
        printf 'ok    %s\n' "$description"
    else
        printf 'FAIL  %s\n' "$description"
        failed=1
    fi
}

# Every variable the binary reads to decide where things go, so that neither the
# machine's own configuration nor its real store can be reached.
isolated() {
    env -u LETEO_MODEL_DIR -u XDG_CONFIG_HOME -u APPDATA -u USERPROFILE \
        -u CLAUDE_CONFIG_DIR -u DSH_HOME -u PI_CODING_AGENT_DIR \
        HOME="$ROOT/home" LETEO_DATA_DIR="$ROOT/data" "$@"
}

install_into() {
    prefix="$1"
    isolated LETEO_INSTALL_DIR="$prefix/bin" LETEO_VERSION="$VERSION" \
        LETEO_BASE_URL="file://$ROOT/dist" sh scripts/install.sh >"$ROOT/install.log" 2>&1 \
        || { cat "$ROOT/install.log"; echo "install.sh failed" >&2; exit 1; }
}

model_names() {
    # The names the binary checks, read from the one list in the source.
    sed -n '/pub const MODEL_FILES/,/^];/p' src/semantic/mod.rs | sed -n 's/^ *"\([a-z0-9._]*\)",$/\1/p' \
        | grep '\.'
}

verified_at() {
    # The detail doctor gives names the directory it found the model in, which has
    # to be the one install.sh wrote: `../share/leteo/model` from the binary.
    # Blanks are stripped to read the JSON on one line, which is also why the
    # sentence below has none.
    isolated "$1/bin/leteo" doctor 2>/dev/null | tr -d ' \n' \
        | grep -o '"code":"semantic_model","ok":true,"detail":"[^"]*' \
        | grep -q 'verifiedat[^"]*/bin/\.\./share/leteo/model$'
}

none_left() {
    # none_left <prefix>
    for name in $(model_names); do
        [ ! -e "$1/share/leteo/model/$name" ] || return 1
    done
    [ ! -e "$1/share/leteo" ] && [ -d "$1/share" ]
}

[ "$(model_names | wc -l)" -ge 3 ] || { echo "install check could not run: no model names found in src/semantic/mod.rs" >&2; exit 2; }

# Something of somebody else's in share/, which no removal may take.
seed_share() { mkdir -p "$1/share" && : > "$1/share/someone-elses"; }

echo "-- installed, then removed by leteo uninstall"
P="$ROOT/a"
seed_share "$P"
install_into "$P"
for name in $(model_names); do
    check "install.sh put $name under share/leteo/model" test -f "$P/share/leteo/model/$name"
done
check "the installed binary's doctor verifies the model there" verified_at "$P"
isolated "$P/bin/leteo" uninstall --yes >"$ROOT/uninstall.log" 2>&1 || { cat "$ROOT/uninstall.log"; failed=1; }
check "leteo uninstall removed the model and share/leteo, and not share/" none_left "$P"
check "and left what was in share/" test -f "$P/share/someone-elses"

echo "-- installed, then removed by uninstall.sh with the binary there"
P="$ROOT/b"
seed_share "$P"
install_into "$P"
check "doctor verifies the model" verified_at "$P"
isolated LETEO_INSTALL_DIR="$P/bin" sh "$P/bin/uninstall.sh" --yes >"$ROOT/uninstall.log" 2>&1 || { cat "$ROOT/uninstall.log"; failed=1; }
check "uninstall.sh removed the model and share/leteo, and not share/" none_left "$P"
check "and the binary" test ! -e "$P/bin/leteo"

echo "-- installed, then removed by uninstall.sh once the binary is gone"
P="$ROOT/c"
seed_share "$P"
install_into "$P"
rm -f "$P/bin/leteo"
isolated LETEO_INSTALL_DIR="$P/bin" sh "$P/bin/uninstall.sh" --yes >"$ROOT/uninstall.log" 2>&1 || { cat "$ROOT/uninstall.log"; failed=1; }
check "uninstall.sh alone removed the model and share/leteo, and not share/" none_left "$P"

if [ "$failed" -ne 0 ]; then
    echo "install check FAILED (repository: $REPO)"
    exit 1
fi
echo "install check passed"
