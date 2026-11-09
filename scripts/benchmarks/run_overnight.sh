#!/bin/sh
# Unattended overnight run of the machine-only benchmarks. Start it with: caffeinate -ims scripts/benchmarks/run_overnight.sh
# Stages run in order and a failed stage never stops the later ones. Before each stage the script waits (up to 15 minutes) for the machine to be quiet, and records whether it was.
# Results written by an earlier daytime run are moved to raw/superseded_daytime/ only after the replacing stage succeeds, so a failed stage never leaves a gap.
# Uses no network, no sudo, no paid API, and starts no Basil process. It never touches ~/.basil.
cd "$(dirname "$0")/../.." || exit 1
ROOT=$(pwd)
RAW="$ROOT/local/w. Documentation/a.GTM_Docs/Feature_Analysis/Benchmarks/raw"
LOG=/tmp/basil-bench-logs/overnight.log
STATUS=/tmp/basil-bench-logs/overnight_status.txt
mkdir -p /tmp/basil-bench-logs "$RAW/superseded_daytime"
: > "$STATUS"
export PYTHONPATH="scripts:backend/src" PYTHONUNBUFFERED=1
PY=.venv/bin/python

say_status() { echo "$(date '+%F %T') $*" | tee -a "$STATUS" >> "$LOG"; }

wait_quiet() {
  waited=0
  while [ "$waited" -lt 900 ]; do
    idle=$(top -l 2 -n 0 -s 5 | grep "CPU usage" | tail -1 | sed -E 's/.* ([0-9.]+)% idle.*/\1/')
    if [ "${idle%.*}" -ge 90 ] 2>/dev/null; then say_status "quiet ok before $1 (idle ${idle}%)"; return 0; fi
    waited=$((waited + 60)); sleep 55
  done
  say_status "NOT QUIET before $1 after 15 minutes (idle ${idle}%); running anyway"
}

stage() {
  name=$1; pattern=$2; shift 2
  wait_quiet "$name"
  marker=$(mktemp); say_status "START $name"
  "$@" >> "$LOG" 2>&1; code=$?
  say_status "END $name exit $code"
  if [ "$code" -eq 0 ] && [ -n "$pattern" ]; then
    find "$RAW" -maxdepth 1 -name "$pattern" ! -newer "$marker" -exec mv {} "$RAW/superseded_daytime/" \;
  fi
  rm -f "$marker"
}

say_status "overnight run begins"
stage wake_word "wake_word_eval__*__full__*.json" "$PY" -m benchmarks.wake_word_eval --negative-minutes 60
stage dictation_latency "dictation_latency_controlled__*__full__*.json" "$PY" -m benchmarks.dictation_latency_controlled
stage dictation_wer "dictation_wer__*__full__*.json" "$PY" -m benchmarks.dictation_wer
for id in Qwen-qwen35-4b-q4km Qwen-qwen3-8b-instruct-q4km Qwen-qwen3-coder-30b-a3b-instruct-q4km Qwen-qwen36-35b-a3b-ud-q4km; do
  stage "llama_$id" "llm_bench_llama__*__${id}__full__*.json" "$PY" -m benchmarks.llm_bench_llama --model-id "$id"
done
for pair in qwen35-4b qwen3-8b qwen35-9b qwen3-30b-a3b qwen36-35b-a3b; do
  stage "mlx_pair_$pair" "" "$PY" -m benchmarks.mlx.run_pair --pair "$pair"
done
stage mlx_verdict "" "$PY" -m benchmarks.mlx.mlx_verdict
stage render "" "$PY" -m benchmarks.common.render
say_status "overnight run complete"
