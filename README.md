# Basil

Basil is a macOS AI assistant with a native Swift client, a local Python/FastAPI backend, and embedded web components. It supports local models and bring-your-own-provider keys. Basil Cloud is optional and is not required for local or BYOK use. See [Privacy and data flow](docs/privacy-and-data-flow.md) before selecting a provider, granting macOS permissions, or connecting an external service.

## Features

- **Native macOS Client:** Built in Swift with SwiftUI for a sleek system tray interface and customizable settings.
- **AI Assistance:** Provides transcription, contextual suggestions, and screen capture analysis.
- **Hotkey Integration:** Use hotkeys (e.g. F10 for screen capture and F7 for toggling audio transcription) for rapid interaction.
- **Dynamic Model Management:** Supports selection and live updating of vision, transcription, and reasoning models. Models are downloaded on-demand using a Python backend and updated with proper cache management.
- **Python-Powered Backend:** Utilizes FastAPI, running background processing (including model downloads) in-process with asyncio, plus structured logging.
- **Transcription History:** Maintains a searchable history of all transcriptions with audio playback capability, allowing users to review, copy, and reuse past transcriptions.

## Prerequisites

- macOS (currently supported only on macOS)
- Swift toolchain / Xcode (for building the native client)
- Python 3.11 or higher
- [Poetry](https://python-poetry.org/) (for Python dependency management)
- Homebrew (for installing system dependencies)
- Required system packages:
  - LLVM (e.g. `brew install llvm`)
  - Tesseract OCR (`brew install tesseract`)
  - FFmpeg is built from the pinned LGPL source by `build/scripts/build_ffmpeg_lgpl.sh`; Homebrew FFmpeg is not required.
  - TBB (`brew install tbb`)

> **Note:** Features that use microphone capture, hotkeys, desktop automation, screen analysis, calendar, or contacts require the corresponding macOS permission. See [Privacy and data flow](docs/privacy-and-data-flow.md#macos-permissions).

## Provider configuration

Set provider credentials in your environment before starting the backend, for example `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, or `GOOGLE_API_KEY`. Basil also supports user-provided keys stored locally under `~/.basil/config/api_keys.json`. No provider credential is included in this repository. Direct-provider requests send their selected input to that provider; local-model inference stays on your Mac. See [Privacy and data flow](docs/privacy-and-data-flow.md#choose-your-model-path) for Basil Cloud and connected-service behavior.

For a community build, do not set `BASIL_DEVELOPER_ID_CERT`; use `build/scripts/build_app.sh --ad-hoc`. Automatic updates are disabled unless a release owner supplies both `BASIL_SPARKLE_FEED_URL` and `BASIL_SPARKLE_PUBLIC_ED_KEY` for a distinct feed. To sign an official build, the release owner supplies `BASIL_DEVELOPER_ID_CERT`; notarization also requires `BASIL_APPLE_TEAM_ID` and a local `BASIL_NOTARY_KEYCHAIN_PROFILE`. To publish a DMG with `--upload`, configure `s3cmd` locally and set `BASIL_DO_SPACES_BUCKET` plus `BASIL_RELEASE_DOWNLOAD_BASE_URL`; `BASIL_RELEASE_NOTES_FILE` selects the local release-notes file. Official signing identities, notarization credentials, update-feed keys, and hosted-service credentials are not part of the source distribution.

## Installation and Setup

1. **Clone the Repository:**

   ```bash
   git clone <repository-url> basil
   cd basil
   ```

2. **Install System Dependencies:**

   ```bash
   brew install llvm tesseract tbb
   ```

3. **Set Up LLVM Environment:**

   ```bash
   export LLVM_CONFIG=/opt/homebrew/opt/llvm/bin/llvm-config
   ```

4. **Install Python Dependencies Using Poetry:**
   
   ```bash
   poetry install
   ```

## Quick Setup for Development

The project has three canonical source surfaces:
- **Swift client:** `client/`
- **Python backend:** `backend/`
- **Embedded web components:** `web-components/`

All source and build inputs use only `backend/`, `client/`, `web-components/`, `build/`, and `scripts/`. See `docs/repository-layout.md`.

1. Start the full local development environment from the repository root:

   ```bash
   ./dev.sh
   ```

   `./dev.sh` builds the verified LGPL FFmpeg dependency when needed, rebuilds every embedded web surface, starts the local Python backend, builds the Swift client, and launches Basil. It intentionally replaces an existing Basil development backend/client session.

2. Create a local signed release after placing owner-only release exports in `local/release.env`:

   ```bash
   ./release.sh --create-dmg --version "$BASIL_RELEASE_VERSION"
   ```

   `--notarize` contacts Apple and `--upload` publishes artifacts; neither is part of ordinary local development.

## Usage

1. **Starting the Application:**

   When you run the development script (`./dev.sh`), the backend is started and the client app is built and launched automatically. Alternatively, you can run the Python backend separately with Poetry and build the Swift client using Swift Package Manager.

2. **Interacting with Basil:**

   - The Basil icon will appear in your system tray.
   - Click the icon to access options such as Start/Stop Monitoring, Settings, and Quit.
   - Use **F10** to capture and analyze screen content.
   - Use **F7** to toggle audio transcription.
   - Access your transcription history in the Settings panel under the Transcription tab.

3. **Transcription History:**

   - View a list of your past transcriptions with date, duration, and preview text.
   - Filter transcriptions by time period (24 hours, 7 days, 30 days, or all time).
   - Play back the original audio for any transcription.
   - View the full text of any transcription and copy it to your clipboard.
   - Transcriptions are stored locally in a SQLite database for privacy and quick access.

4. **Model Management:**

   - The app dynamically downloads and manages AI models (for transcription, vision, and reasoning).
   - When a model is removed via the settings (or via the API), both the local copy and the Hugging Face cache are cleared to ensure a fresh download if needed.

## Development

- **Adding New Dependencies:**

  ```bash
  poetry add package_name
  ```
  
- **Development Dependencies:**

  ```bash
  poetry add --group dev package_name
  ```
  
- **Running Tests:**

  The project employs PyTest for testing along with MyPy for type checking.

- **Formatting and Linting:**

  The project uses Black for code formatting and Flake8 for linting. Please adhere to the established coding guidelines.

## Distribution Options

### Option 1: Bundled Application (Recommended)
Bundle the Swift client and Python backend into a standalone macOS app. Tools such as PyInstaller (for the backend) and Xcode (for the client) can be used.

### Option 2: Docker Container
You can create a Docker image that contains the backend and necessary dependencies. For example:

```dockerfile
FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    llvm \
    tbb \
    ffmpeg \
    tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

# Install Poetry and application
COPY . /app
WORKDIR /app
RUN pip install poetry && poetry install
```

### Option 3: Platform-Specific Packages
- **macOS:** Create a .app bundle using tools like py2app or Xcode integration.
- **Linux / Windows:** Bundle the backend with platform-specific packaging tools (.deb, .rpm, or installer packages).

## License

Copyright 2026 Stratten Waldt. Basil is licensed under Apache-2.0; see `LICENSE`. The Basil name and official-distribution identity are governed separately by `TRADEMARK.md`.