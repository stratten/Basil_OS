#!/usr/bin/env bash
set -euo pipefail

# Fails when any Mach-O file under the given directory loads a library by an absolute path outside macOS. Such a path exists only on the build machine, so the library fails to load on other Macs. LC_RPATH entries are not checked because dyld skips search paths that do not exist.

if [[ $# -ne 1 ]]; then
    echo "Usage: $0 <path/to/App.app or bundle directory>" >&2
    exit 2
fi

readonly BUNDLE_PATH="${1%/}"
if [[ ! -d "$BUNDLE_PATH" ]]; then
    echo "Bundle not found: $BUNDLE_PATH" >&2
    exit 1
fi

offenders="$(mktemp)"
trap 'rm -f "$offenders"' EXIT
checked=0

while IFS= read -r -d '' file; do
    [[ "$(file -b --mime-type "$file")" == "application/x-mach-binary" ]] || continue
    checked=$((checked + 1))
    otool -l "$file" | awk '
        /^ *cmd LC_(LOAD|LOAD_WEAK|REEXPORT|LAZY_LOAD|LOAD_UPWARD)_DYLIB$/ { want = 1; next }
        /^ *cmd / { want = 0 }
        want == 1 && $1 == "name" { print $2; want = 0 }
    ' | while IFS= read -r dependency; do
        case "$dependency" in
            @rpath/*|@loader_path/*|@executable_path/*|/usr/lib/*|/System/Library/*) ;;
            *) printf '%s -> %s\n' "${file#"$BUNDLE_PATH"/}" "$dependency" >> "$offenders" ;;
        esac
    done
done < <(find "$BUNDLE_PATH" -type f \( -name '*.dylib' -o -name '*.so' -o -perm -111 \) -print0)

if [[ -s "$offenders" ]]; then
    echo "Found $(wc -l < "$offenders" | tr -d ' ') library references that resolve only on the build machine:" >&2
    cat "$offenders" >&2
    exit 1
fi

if [[ "$checked" -eq 0 ]]; then
    echo "No Mach-O files found under $BUNDLE_PATH." >&2
    exit 1
fi

echo "Checked $checked Mach-O files; every library reference resolves inside the bundle or macOS."
