#!/bin/bash
# Run cloc sorted by code lines, grouped into frontend and backend sections.
# Uses git ls-files so the scan stays fast and avoids generated/untracked output.
# Usage: ./00_run_cloc.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
TIMESTAMP=$(date +"%Y-%m-%d_%H%M")
OUTPUT_FILE="$SCRIPT_DIR/${TIMESTAMP}_frontend_backend_cloc_report.txt"
FRONTEND_FILE_LIST="$(mktemp "$SCRIPT_DIR/.${TIMESTAMP}_frontend_cloc_files_XXXXXX")"
BACKEND_FILE_LIST="$(mktemp "$SCRIPT_DIR/.${TIMESTAMP}_backend_cloc_files_XXXXXX")"

cleanup() {
  rm -f "$FRONTEND_FILE_LIST" "$BACKEND_FILE_LIST"
}
trap cleanup EXIT

build_file_list() {
  local section_pattern="$1"
  local output_file="$2"

  git ls-files | awk -v section_pattern="$section_pattern" '
    $0 ~ section_pattern &&
    !/(^|\/)(node_modules|\.venv|dist|build|coverage|__pycache__|\.mypy_cache|\.pytest_cache|htmlcov|staticfiles|media|artifacts|public|z_logs_docs)\// &&
    !/(^|\/)(package-lock\.json|poetry\.lock|schema\.yml|api-schema\.yaml)$/ &&
    !/(\.svg|\.md)$/
  ' > "$output_file"
}

write_sorted_cloc_section() {
  local title="$1"
  local file_list="$2"
  local file_count

  file_count=$(wc -l < "$file_list" | tr -d ' ')

  {
    echo "$title"
    printf '=%.0s' $(seq 1 "${#title}")
    echo ""
    echo "Tracked files analyzed: $file_count"
    echo ""
  } >> "$OUTPUT_FILE"

  if [[ "$file_count" == "0" ]]; then
    echo "No tracked files matched this section." >> "$OUTPUT_FILE"
    echo "" >> "$OUTPUT_FILE"
    return
  fi

  cloc --by-file --skip-uniqueness --list-file="$file_list" 2>/dev/null | awk '
    /^---/   { sep[++s]=$0; next }
    /^SUM:/  { sum=$0; next }
    /^File / || /Language/ { hdr[++h]=$0; next }
    /^[a-zA-Z.\/]/ { data[++d]=$0; code[d]=$NF; next }
    NF==0 { next }
    { other[++o]=$0 }
    END {
      # Print header
      for (i=1; i<=h; i++) print hdr[i]
      if (s>=1) print sep[1]

      # Sort data lines by code column (last field) descending.
      # Simple insertion sort.
      for (i=2; i<=d; i++) {
        key = code[i]; kd = data[i]
        j = i - 1
        while (j >= 1 && code[j]+0 < key+0) {
          code[j+1] = code[j]; data[j+1] = data[j]
          j--
        }
        code[j+1] = key; data[j+1] = kd
      }
      for (i=1; i<=d; i++) print data[i]

      # Print footer
      if (s>=2) print sep[2]
      if (sum) print sum
      if (s>=3) print sep[3]
    }
  ' >> "$OUTPUT_FILE"

  echo "" >> "$OUTPUT_FILE"
}

cd "$PROJECT_ROOT"

build_file_list "^(web-components|client)/" "$FRONTEND_FILE_LIST"
build_file_list "^Basil/" "$BACKEND_FILE_LIST"

: > "$OUTPUT_FILE"
write_sorted_cloc_section "Frontend" "$FRONTEND_FILE_LIST"
write_sorted_cloc_section "Backend" "$BACKEND_FILE_LIST"

echo ""
echo "Report saved to: $OUTPUT_FILE"
echo ""
sed -n '1,45p' "$OUTPUT_FILE"
echo ""
echo "... (truncated, see full file for complete frontend and backend sections)"
