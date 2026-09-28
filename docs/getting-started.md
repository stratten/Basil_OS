# Getting started

Basil is currently a macOS application. Its development environment combines a native Swift client, a local Python/FastAPI backend, and embedded React/Vite web surfaces.

## Prerequisites

Install Xcode or the Swift toolchain, Python 3.11, [Poetry](https://python-poetry.org/), Node.js with npm, and Homebrew. The repository currently constrains Python to the 3.11 release line, so do not assume that a newer Python version is a drop-in replacement for local development.

The backend and packaged app also require the following Homebrew packages:

```bash
brew install llvm tesseract tbb libsndfile portaudio coreutils
```

`dev.sh` builds the pinned LGPL FFmpeg dependency from source when it is missing. Do not substitute a Homebrew FFmpeg for the packaged build path.

On Apple Silicon, point Python packages that require LLVM at Homebrew's LLVM installation:

```bash
export LLVM_CONFIG=/opt/homebrew/opt/llvm/bin/llvm-config
```

If Homebrew is installed somewhere other than `/opt/homebrew`, use its actual LLVM path instead. The value is an environment variable for the terminal session that installs or builds the Python dependency; it is not a Basil setting.

## Clone and prepare the repository

```bash
git clone git@github.com:stratten/Basil_OS.git basil
cd basil
poetry install
```

The repository includes source code, lockfiles, and build scripts. It intentionally does not include model weights, provider credentials, local databases, runtime logs, generated web bundles, or packaged application artifacts. Model downloads and provider configuration happen locally after you choose the relevant model path.

Node.js and npm are required because the development launch rebuilds embedded web surfaces. You do not normally need to hand-edit or manually copy their generated `dist/` files; the canonical asset builders stage the bundles consumed by the native app.

## Start a local development session

Run the following command from the repository root:

```bash
./dev.sh
```

The script checks or installs Poetry dependencies when needed, builds the verified LGPL FFmpeg dependency, rebuilds the embedded web surfaces, starts the local backend, builds the Swift client, packages a development app, and launches it. The terminal session remains responsible for the local backend while the development app is running.

`./dev.sh` is not a harmless refresh command. It deliberately terminates existing Basil development backend processes and development-client instances before creating its own session. Do not run it while another person or workflow is using a shared local Basil development session, during a recording, or while an active task depends on that development backend.

For a normal local session, quit the app or press Control-C in the terminal to let the script clean up its backend process. If the native app exits unexpectedly, inspect the terminal output before rerunning the script; repeated launches can mask the original error and replace a useful development session.

## First launch and permissions

Basil continues to work when optional permissions are declined, but the related capability remains unavailable. Start with the smallest set of permissions for the feature you want to test, then grant additional access only when you decide to use the related workflow:

- **Microphone** for live transcription, meetings, and voice-driven workflows.
- **Input Monitoring** for global hotkeys.
- **Accessibility** and **Apple Events / Automation** for desktop automation.
- **Screen Recording** for screen and window capture, OCR, and visual analysis.
- **Calendar** for meeting enrichment, calendar join prompts, and calendar-matched meeting detection.
- **Contacts** for optional personalization of drafts and recipients.

macOS may require you to restart the development app after granting Screen Recording. You can change or revoke permissions later in System Settings → Privacy & Security. Revoking a permission leaves unrelated Basil features available but prevents the dependent capability from completing its work.

Do not confuse Meeting Detection with meeting recording. Detection can observe eligible process audio activity without recording audio. A recording starts only when you choose the meeting action or configure an automatic detected-meeting flow. See [Capabilities](capabilities.md#meeting-detection) for the detection behavior and its single-active-meeting safeguard.

## Choose a model path

You can use local models, direct-provider models with your own provider key, custom models, or Basil Cloud where available:

- **Local models** keep inference on the Mac after the model has been downloaded.
- **Direct-provider models** use the key you configure and send the request content required by that provider.
- **Custom models** use the endpoint or runtime you configure.
- **Basil Cloud** is an optional account-backed path and is not required for local or direct-provider use.

Choose a model separately for the capability that needs it. A reasoning model does not automatically configure transcription, and enabling a provider does not turn on every model it offers. Read [Privacy and data flow](privacy-and-data-flow.md) before choosing a provider, connecting a service, or enabling an automation capability.

Configure models, provider keys, and default behavior in Settings. The [Configuration guide](configuration.md) explains the available settings groups, the distinction between provider enablement and “use your own API key,” and the difference between enabling a capability and starting a runtime monitor.

## Use the application incrementally

After the app opens, begin with a local, low-permission workflow such as opening the Basil Board, choosing a local model, or reviewing Settings. Add Screen Recording when you need capture, Microphone when you need live transcription, and automation permissions only when you intend to automate a supported workflow.

For meeting work, use **Meeting / Call Transcription** when you want to start a recording yourself. Configure Meeting Detection separately if you want prompts or automatic behavior around likely calls. For agent work, begin with an Agent Task or a conversation, then review any request for an external action before approval.

## Next steps

- Read [Capabilities](capabilities.md) to choose a workflow and understand its persistence, requirements, and limits.
- Read [Configuration](configuration.md) before enabling models, connections, automation, or background capabilities.
- Read [Privacy and data flow](privacy-and-data-flow.md) before choosing a provider, connecting a service, or deleting local data.
- Read [Development](development.md) before changing code, building embedded assets, or preparing a release.
