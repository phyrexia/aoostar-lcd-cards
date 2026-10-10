#!/bin/sh
# Install asterctl (https://github.com/zehnm/aoostar-rs, MIT OR Apache-2.0) at the
# version pinned in asterctl.version. Idempotent: if that version is already installed
# it does nothing.
#
#   sudo scripts/install-asterctl.sh                      # auto: release on Linux x86_64, else source
#   sudo scripts/install-asterctl.sh --from release       # prebuilt binary, SHA-256 checked
#   sudo scripts/install-asterctl.sh --from source        # cargo install at the pinned commit
#   scripts/install-asterctl.sh --prefix "$HOME/.local"   # no root needed
#
# Environment: ASTERCTL_RELEASE_BASE_URL overrides the download base URL (for a mirror);
# the checksum from asterctl.version is enforced anyway.
set -eu

SCRIPT_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
ROOT_DIR=$(dirname -- "$SCRIPT_DIR")
VERSION_FILE="$ROOT_DIR/asterctl.version"
PREFIX=/usr/local
FROM=auto
FORCE=0
PRINT=0

usage() {
	sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'
	cat <<'EOF'
Options:
  --from auto|release|source   how to obtain the binary (default: auto)
  --prefix DIR                 install into DIR/bin (default: /usr/local)
  --version-file FILE          pin file (default: asterctl.version next to scripts/)
  --force                      reinstall even if the pinned version is present
  --print-pin                  print the pinned values and exit
  -h, --help                   this help
EOF
}

log() { echo "install-asterctl: $*" >&2; }
die() {
	log "error: $*"
	exit 1
}

while [ $# -gt 0 ]; do
	case "$1" in
	--from)
		[ $# -ge 2 ] || die "--from needs a value"
		FROM=$2
		shift 2
		;;
	--prefix)
		[ $# -ge 2 ] || die "--prefix needs a value"
		PREFIX=$2
		shift 2
		;;
	--version-file)
		[ $# -ge 2 ] || die "--version-file needs a value"
		VERSION_FILE=$2
		shift 2
		;;
	--force)
		FORCE=1
		shift
		;;
	--print-pin)
		PRINT=1
		shift
		;;
	-h | --help)
		usage
		exit 0
		;;
	*) die "unknown option: $1 (see --help)" ;;
	esac
done

[ -f "$VERSION_FILE" ] || die "version file not found: $VERSION_FILE"

# Read KEY=VALUE without executing the file.
pin() {
	value=$(sed -n "s|^$1=\([A-Za-z0-9._:/+-]*\)\$|\1|p" "$VERSION_FILE" | tail -n 1)
	[ -n "$value" ] || die "$1 missing or malformed in $VERSION_FILE"
	printf '%s' "$value"
}

REPO=$(pin ASTERCTL_REPO)
TAG=$(pin ASTERCTL_TAG)
COMMIT=$(pin ASTERCTL_COMMIT)
SHA256=$(pin ASTERCTL_LINUX_X64_SHA256)
printf '%s' "$TAG" | grep -Eq '^v[0-9]+\.[0-9]+\.[0-9]+$' || die "bad ASTERCTL_TAG: $TAG"
printf '%s' "$COMMIT" | grep -Eq '^[0-9a-f]{40}$' || die "bad ASTERCTL_COMMIT: $COMMIT"
printf '%s' "$SHA256" | grep -Eq '^[0-9a-f]{64}$' || die "bad ASTERCTL_LINUX_X64_SHA256"
VERSION=${TAG#v}

if [ "$PRINT" = 1 ]; then
	printf 'repo=%s\ntag=%s\ncommit=%s\nsha256=%s\n' "$REPO" "$TAG" "$COMMIT" "$SHA256"
	exit 0
fi

TARGET="$PREFIX/bin/asterctl"

installed_version() {
	"$1" --version 2>/dev/null | sed -n 's/^asterctl \([0-9][0-9.]*\).*/\1/p' | head -n 1
}

if [ "$FORCE" = 0 ] && [ -x "$TARGET" ] && [ "$(installed_version "$TARGET" || true)" = "$VERSION" ]; then
	log "asterctl $VERSION already installed at $TARGET"
	exit 0
fi

if [ "$FROM" = auto ]; then
	if [ "$(uname -s)" = Linux ] && [ "$(uname -m)" = x86_64 ]; then
		FROM=release
	else
		FROM=source
	fi
fi

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT INT TERM

sha256_of() {
	if command -v sha256sum >/dev/null 2>&1; then
		sha256sum "$1" | cut -d ' ' -f 1
	elif command -v shasum >/dev/null 2>&1; then
		shasum -a 256 "$1" | cut -d ' ' -f 1
	else
		die "need sha256sum or shasum"
	fi
}

fetch() {
	if command -v curl >/dev/null 2>&1; then
		curl -fsSL --retry 3 -o "$2" "$1"
	elif command -v wget >/dev/null 2>&1; then
		wget -q -O "$2" "$1"
	else
		die "need curl or wget"
	fi
}

case "$FROM" in
release)
	BASE=${ASTERCTL_RELEASE_BASE_URL:-https://github.com/zehnm/aoostar-rs/releases/download}
	ARCHIVE="asterctl-$TAG-Linux-x64.tar.gz"
	log "downloading $ARCHIVE"
	fetch "$BASE/$TAG/$ARCHIVE" "$TMP/$ARCHIVE" || die "download failed: $BASE/$TAG/$ARCHIVE"
	GOT=$(sha256_of "$TMP/$ARCHIVE")
	[ "$GOT" = "$SHA256" ] || die "checksum mismatch for $ARCHIVE: expected $SHA256, got $GOT"
	mkdir "$TMP/x"
	tar -xzf "$TMP/$ARCHIVE" -C "$TMP/x"
	[ -f "$TMP/x/asterctl" ] || die "asterctl not found inside $ARCHIVE"
	BIN="$TMP/x/asterctl"
	;;
source)
	command -v cargo >/dev/null 2>&1 || die "cargo not found: install Rust >= 1.88 (https://rustup.rs), pkg-config and libudev-dev, or use --from release on Linux x86_64"
	log "building asterctl $TAG (commit $COMMIT) with cargo"
	cargo install --locked --git "$REPO" --rev "$COMMIT" --root "$TMP/root" asterctl
	BIN="$TMP/root/bin/asterctl"
	;;
*) die "--from must be auto, release or source (got $FROM)" ;;
esac

install -d "$PREFIX/bin"
install -m 0755 "$BIN" "$TARGET"
# The license texts travel with the binary.
if [ -d "$ROOT_DIR/licenses/asterctl" ]; then
	install -d "$PREFIX/share/doc/asterctl"
	install -m 0644 "$ROOT_DIR"/licenses/asterctl/LICENSE-* "$PREFIX/share/doc/asterctl/"
fi

GOT_VERSION=$(installed_version "$TARGET" || true)
if [ "$GOT_VERSION" = "$VERSION" ]; then
	log "installed asterctl $VERSION at $TARGET"
elif [ -z "$GOT_VERSION" ]; then
	log "installed $TARGET, but it does not run on this machine (missing libudev1?)."
	log "check with: $TARGET --version"
else
	die "installed binary reports version $GOT_VERSION, expected $VERSION"
fi
