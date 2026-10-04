# Verifying repository builds

Every push to `main` builds Basil on GitHub-hosted macOS runners, signs and notarizes it with the project's Developer ID, and publishes the result as the `main-latest` pre-release on this repository's Releases page. Each new push replaces the previous build. This page explains how to confirm that a downloaded build came from the code you can read here.

## Who this is for

Use a repository build if you want a ready-to-run app but also want to confirm what it was built from. If you would rather build Basil yourself, follow [Getting started](getting-started.md). If you want automatic updates, use the release from the website instead.

## What you need

- A Mac with Apple Silicon.
- A current version of the [GitHub CLI](https://cli.github.com/), signed in with `gh auth login`. Run `gh attestation verify --help` and confirm it lists `--source-digest`; if it does not, update `gh` first.
- A clone of this repository if you also want to run the local checks script.

## Steps

1. Open the `main-latest` pre-release on the repository's Releases page. Note the full commit SHA in the release notes, then download `Basil-main-<short-sha>.dmg` and `SHA256SUMS.txt`.

2. Confirm the file matches the published checksum:

```bash
shasum -a 256 -c SHA256SUMS.txt
```

3. Verify the build-provenance attestation. Replace `<commit-sha>` with the full 40-character SHA from the release notes:

```bash
gh attestation verify Basil-main-<short-sha>.dmg \
  --repo stratten/Basil_OS \
  --signer-workflow stratten/Basil_OS/.github/workflows/validate.yml \
  --source-ref refs/heads/main \
  --source-digest <commit-sha> \
  --deny-self-hosted-runners
```

A successful result means GitHub's signing service recorded that this exact file was produced by the `validate.yml` workflow in this repository, running on a GitHub-hosted runner, from that commit on `main`. Add `--format json` to see the full record, including the workflow run that built it.

4. Read the code at that commit, for example `https://github.com/stratten/Basil_OS/tree/<commit-sha>`. Compare it with anything else you care about.

5. Optionally, check the app's signature and stamped commit from a clone of this repository:

```bash
build/scripts/verify_release_artifact.sh Basil-main-<short-sha>.dmg <commit-sha>
```

The script confirms the notarization ticket, the Developer ID signature, Gatekeeper's assessment, the `BasilSourceCommit` value inside the app, and that automatic updates are turned off.

## What this proves

- The file you downloaded is byte-for-byte the file the workflow produced.
- The workflow that produced it is the `validate.yml` file in this repository at the named commit, which you can read.
- That run also passed the repository's backend, web-component, and client tests, because the build job depends on them.
- The app was signed with the project's Developer ID and notarized by Apple.

## What this does not prove

- Builds are not reproducible. Building the same commit yourself will not produce an identical file, because signing timestamps, notarization tickets, and Homebrew package versions differ between runs. The attestation ties the file to the workflow and commit; it does not let you re-derive the same bytes.
- Homebrew packages and Python wheels are fetched at build time. The workflow pins the Python runtime, FFmpeg source, Poetry lock file, and npm lock files, but Homebrew formulas follow the runner's current versions.
- The attestation describes how the file was made. It is not a security review of the code.

## Repository builds and website builds

Both are signed with the same Developer ID and use the same bundle identifier, so macOS treats them as the same app and they share settings and data. Install only one at a time.

Repository builds do not check for updates. To move to a newer build, download the current `main-latest` release again and verify it. Website builds update themselves through Sparkle and are released on a separate schedule; they are built by the release owner rather than by this workflow, so the steps on this page do not apply to them.

`main-latest` follows the newest code on `main`, which can include changes that have not reached a website release yet. Those changes can upgrade Basil's stored data, so moving from a repository build back to an older website release is not supported; wait for a website release at least as new as your repository build.
