#!/usr/bin/env bash
set -euo pipefail

readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
readonly FFMPEG_VERSION="7.1.5"
readonly FFMPEG_ARCHIVE="ffmpeg-${FFMPEG_VERSION}.tar.xz"
readonly FFMPEG_URL="https://ffmpeg.org/releases/${FFMPEG_ARCHIVE}"
readonly FFMPEG_SHA256="de668509caf9e35e3cd162473441fdb29538c6d96ed080292b3cf9e6fc5d558f"
readonly FFMPEG_PREFIX="${1:-$REPO_ROOT/build/third_party/ffmpeg-lgpl}"
readonly FFMPEG_CACHE_DIR="${BASIL_FFMPEG_CACHE_DIR:-$REPO_ROOT/build/cache}"
readonly FFMPEG_ARCHIVE_PATH="$FFMPEG_CACHE_DIR/$FFMPEG_ARCHIVE"
readonly FFMPEG_SOURCE_DIR="$FFMPEG_CACHE_DIR/ffmpeg-${FFMPEG_VERSION}"

for command in curl shasum tar make xcrun; do
    command -v "$command" >/dev/null || {
        echo "Required command is unavailable: $command" >&2
        exit 1
    }
done

mkdir -p "$FFMPEG_CACHE_DIR"
if [[ ! -f "$FFMPEG_ARCHIVE_PATH" ]]; then
    curl --fail --location --proto '=https' --tlsv1.2 "$FFMPEG_URL" --output "$FFMPEG_ARCHIVE_PATH"
fi

expected_checksum="${FFMPEG_SHA256}  ${FFMPEG_ARCHIVE_PATH}"
printf '%s\n' "$expected_checksum" | shasum -a 256 -c -

rm -rf "$FFMPEG_SOURCE_DIR"
tar -xJf "$FFMPEG_ARCHIVE_PATH" -C "$FFMPEG_CACHE_DIR"

pushd "$FFMPEG_SOURCE_DIR" >/dev/null
./configure \
    --prefix="$FFMPEG_PREFIX" \
    --arch=arm64 \
    --target-os=darwin \
    --enable-shared \
    --disable-static \
    --disable-doc \
    --disable-ffplay \
    --disable-sdl2 \
    --disable-xlib \
    --disable-libxcb \
    --disable-gpl \
    --disable-nonfree \
    --disable-debug \
    --enable-audiotoolbox \
    --enable-videotoolbox \
    --extra-ldflags="-Wl,-headerpad_max_install_names"
make -j"$(sysctl -n hw.ncpu)"
make install
popd >/dev/null

"$FFMPEG_PREFIX/bin/ffmpeg" -version | grep --quiet -- '--disable-gpl' || {
    echo "The built FFmpeg binary is not configured with --disable-gpl." >&2
    exit 1
}
"$FFMPEG_PREFIX/bin/ffmpeg" -L 2>&1 | grep --quiet 'GNU Lesser General Public' || {
    echo "The built FFmpeg binary does not report an LGPL license." >&2
    exit 1
}

cp "$FFMPEG_SOURCE_DIR/COPYING.LGPLv2.1" "$FFMPEG_PREFIX/"
cp "$FFMPEG_SOURCE_DIR/COPYING.LGPLv3" "$FFMPEG_PREFIX/"
echo "Built and verified LGPL-only FFmpeg ${FFMPEG_VERSION} at $FFMPEG_PREFIX"
