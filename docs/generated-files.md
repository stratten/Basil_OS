# Generated files and build output

Do not commit `api_spec.json`, `generated_models/`, Vite `dist/` folders, files under `client/Sources/Resources/*WebAssets/assets/`, application bundles, runtime Python distributions, model weights, or local databases. The repository includes their source inputs and build scripts instead.

The canonical web asset builder is `scripts/build-agent-task-assets.sh`. It runs the supported Vite builds and stages their generated JS/CSS in the Swift resource folders consumed by a packaged app. It must be run before creating a client application bundle.

The project’s prior `scripts/generate_swift_models.sh` produced an unconsumed `generated_models/` directory, while the active Swift package contains no generated model target. It is deliberately omitted from this public staging tree rather than presented as a working required generator. Restore it only with an active client consumer, an output path within `client/Sources`, and a tested generation command.

`build/scripts/build_ffmpeg_lgpl.sh` is the only supported FFmpeg packaging input. It downloads pinned FFmpeg 7.1.1 source, verifies its SHA-256, compiles with `--disable-gpl` and `--disable-nonfree`, then verifies the resulting binary before `FFmpegBundler` accepts it. The generated FFmpeg tree and packaging output remain ignored.
