# Basil benchmarks

Measurement and validation scripts. They are not part of the shipped app and nothing in Basil calls them. Raw results are written as one JSON file per run under `local/w. Documentation/a.GTM_Docs/Feature_Analysis/Benchmarks/raw/` (override with `BASIL_BENCH_DIR`), and `common/render.py` turns them into Markdown reports.

Import root: scripts add `scripts/` to the path and import `benchmarks.common`, because the virtual environment ships an unrelated `scripts` package. Run everything from the repository root with `PYTHONPATH=scripts .venv/bin/python -m benchmarks.<module>`, and add `:backend/src` to `PYTHONPATH` for modules that import Basil's backend.

## Rules for real runs

- Basil's own background work (activity capture, meeting and audio probes) means "Basil idle" cannot be assumed on a development machine. `common/activity.py` samples the backend, client, and validation-app CPU at 1 Hz. A run window above 100 percent of one core is treated as busy, retried up to three times, and then excluded from medians (the unfiltered lists are kept). Only Basil processes are tracked, not other applications.
- AC power, a 60 second cool-down between engines in the MLX harness, at least three runs where a spread is reported, and the median reported with its range.
- A `--smoke` run proves a script works and is never reportable. A simulated run is labeled simulated.
- No `sudo` tools, no paid API calls, and no real accounts. Anything that records audio or contacts an external system needs the owner's authorization on the day.
- Importing the backend writes a log file under `~/Desktop/BasilDebugLogs`. That is a side effect of the import, not of a benchmark.

## Layout

- `common/`: machine descriptor, result schema, timing and peak-memory helpers, Basil CPU monitor, word-error-rate helpers, Markdown renderer.
- `dictation_log_latency.py`: stop-to-ready latency mined from backend logs.
- `dictation_wer.py` and `dictation_custom_set.py`: word error rate, speed, and memory per speech engine on LibriSpeech and a custom-vocabulary set.
- `dictation_latency_controlled.py`: cold-load and warm transcription latency at fixed audio lengths.
- `quick_assist_app_detection.py`, `quick_assist_cases_native.py`, `quick_assist_cases_browser.py`: labeled table test of the Quick Assist context classifier.
- `llm_bench_llama.py`: llama.cpp speed and memory per local model using Basil's load plan.
- `mlx/`: standalone MLX versus llama.cpp harness. MLX runs in an isolated virtual environment under `~/.basil-bench`, never in Basil's environment. `run_pair.py` runs one pair, `mlx_verdict.py` applies the pre-registered decision rule.
- `meeting_ground_truth.py`: synthetic three-speaker meeting transcription accuracy and Companion gate behavior.
- `wake_word_eval.py`: false accepts and true accepts for the bundled wake-word models.
- `clean_session_defaults.py`: what the code defaults do for activity capture and ambient suggestions.
- `network_passive_sample.py`: passive socket sampling of the running Basil processes.
- `release_verification.py`: checksum and build-attestation check of the latest published release.
- `dependency_analytics_scan.py`: name-based scan of dependency trees for analytics packages.
- `slack_tool_enumeration.py`: counts the embedded Slack server's tools from the code registry.
- `run_overnight.sh`: unattended runner for the machine-only stages (wake word, controlled dictation latency, dictation accuracy, llama.cpp baseline, the five MLX pairs, verdict, reports). Start it with `caffeinate -ims scripts/benchmarks/run_overnight.sh`. It waits for a quiet machine before each stage, logs to `/tmp/basil-bench-logs/overnight.log`, writes stage status to `/tmp/basil-bench-logs/overnight_status.txt`, and moves replaced daytime results to `raw/superseded_daytime/` only after the replacing stage succeeds.
- `browser_fixture/server.py`: loopback fixture site for the live browser matrix, with the checklist in the Benchmarks folder.

## Not built

The ten-task agent suite and the one-hour activity resource sample are not here. They need an isolated backend profile or the owner present. Package status and reasons are in the Benchmarks summary.
