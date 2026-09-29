# Generated files and build output

Do not commit `api_spec.json`, `generated_models/`, Vite `dist/` folders, files under `client/Sources/Resources/*WebAssets/assets/`, application bundles, runtime Python distributions, model weights, or local databases. The repository includes their source inputs and build scripts instead.

This distinction matters because the native app packages the staged WebKit resource folders, while developers edit the React/Vite source under `web-components/`. Editing a built JavaScript or CSS file can appear to fix a local bundle but leaves the real source unchanged and will be overwritten by the next builder run.

## Canonical WebKit builders

`scripts/build-agent-task-assets.sh` is the canonical builder for the main shipped WebKit bundles. It builds and stages:

- Agent Task results and local preview.
- Scheduled-run, model-download, power-user-guide, and setup-resume panels.
- Meeting Detection, ambient suggestions, Basil Board, conversations, Meeting Assistant, and meeting analysis.
- Assistant Session and Assistant Session output history.
- The transcription widget, audio-file transcription, and Agent Task capture input.

The script checks that expected HTML entries and JavaScript assets exist before staging them. If a package build fails or the expected output is absent, it intentionally fails instead of leaving a silently stale or empty native resource bundle.

Several focused WebKit surfaces have their own canonical builders:

- `scripts/build-setup-assistant-assets.sh` for Setup Assistant.
- `scripts/build-profile-editor-assets.sh` for profile, memory, and skills editing.
- `scripts/build-settings-appearance-assets.sh` for Settings.
- `scripts/build-skill-reconciliation-workspace-assets.sh` for the Skill Reconciliation Workspace.

Run the relevant canonical builder after changing its source surface when the change must reach a packaged native resource. A package-local Vite build alone verifies that renderer's source build, but it does not update the staged Swift resource bundle. `dev.sh` runs the complete canonical builder set as part of a full local development launch.

## Generated output and source control

Builder runs can create or update `dist/` output in web-component packages and staged resources under `client/Sources/Resources/`. Review `git status` after a builder run. Generated JavaScript/CSS assets are not source changes to commit; retain the underlying `web-components/` source and the canonical builder changes instead.

The native app bundle, Python distributions, temporary build trees, package-manager caches, models, local databases, runtime status, recordings, and logs are local artifacts. Do not delete an application-data directory merely because it is ignored by Git: it can contain the history, capture, model, or recording material a running instance needs.

## Legacy generator note

The project’s prior `scripts/generate_swift_models.sh` produced an unconsumed `generated_models/` directory, while the active Swift package contains no generated model target. It is deliberately omitted from this public staging tree rather than presented as a working required generator. Restore it only with an active client consumer, an output path within `client/Sources`, and a tested generation command.

## Packaged FFmpeg input

`build/scripts/build_ffmpeg_lgpl.sh` is the only supported FFmpeg packaging input. It downloads pinned FFmpeg 7.1.1 source, verifies its SHA-256, compiles with `--disable-gpl` and `--disable-nonfree`, then verifies the resulting binary before `FFmpegBundler` accepts it. The generated FFmpeg tree and packaging output remain ignored.
