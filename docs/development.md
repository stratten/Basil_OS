# Development

Basil has three primary source surfaces:

- `client/`: the native macOS Swift package and packaged resources.
- `backend/`: the local Python/FastAPI service.
- `web-components/`: React/Vite applications embedded in native WebKit hosts.

Supporting build and release code lives under `scripts/` and `build/scripts/`. Generated bundles, build output, model weights, local databases, logs, and runtime state are not source files; see [Generated files](generated-files.md).

## Architecture

The macOS client owns native window presentation, macOS permissions, audio and screen capture, status-bar controls, and WebKit hosts. The FastAPI backend owns local service APIs, model orchestration, persistence-facing service work, and WebSocket coordination. Embedded web components render interactive application surfaces and communicate with their native hosts through explicit bridge contracts.

The native app is the integration boundary for features that need macOS lifecycle, Accessibility, Screen Recording, microphone, Calendar, Contacts, Apple Events, or window presentation. Do not assume that a browser-only build proves native integration, and do not assume that a native menu action proves a WebKit renderer received its data. Validate the appropriate boundary for the change you make.

Keep these boundaries intact:

- Put reusable backend behavior in `backend/src/api/services/` or `backend/src/api/core/`; route modules are HTTP/WebSocket adapters.
- Keep native lifecycle, permission, and WebKit-host behavior in `client/Sources/`.
- Build embedded UI from `web-components/` source, not from staged files under `client/Sources/Resources/`.
- Treat a model, provider, connection, or permission choice as a product boundary. Trace producers and consumers before changing its contract.

The route inventory is registered in `backend/src/api/routes/registry.py`. The Settings navigation is defined in `web-components/SettingsWebComponents/src/app/SettingsShell.tsx`. Both are useful starting points when locating a capability.

## Local development

From the repository root, install the Python environment and launch the complete development session:

```bash
poetry install
./dev.sh
```

`./dev.sh` is the complete local-development launcher. It builds required components, starts the backend, packages a development app, and launches the client. It also terminates existing Basil development backend/client processes. Do not run it over an active development session you do not intend to replace.

The launch flow also builds the LGPL FFmpeg dependency when necessary, generates development icons, refreshes every canonical WebKit resource bundle, checks the staged output, and waits on the launched native client. Keep the terminal available while the development session is in use. Quit the app or press Control-C to let the launcher perform its cleanup.

For a narrower build, use the component's own package or canonical builder rather than editing staged web assets manually. Do not run `./dev.sh` merely to refresh a renderer when its process replacement would interrupt another active development workflow.

## Choose the correct development surface

Start in `client/` when a change concerns macOS presentation, menu actions, permissions, audio or screen capture, native storage, or a WebKit host. Start in `backend/` when it concerns an API route, durable data, model orchestration, agent lifecycle, scheduling, a connection, or WebSocket behavior. Start in `web-components/` when it concerns an embedded interactive renderer, then trace the bridge and host that supply its data.

Many product features span all three surfaces. For example, a meeting control can need a native entry point, backend state and persistence, a bridge payload, and a WebKit renderer. Identify each producer and consumer before changing a shared data shape or API contract.

## Embedded web assets

The embedded applications are source code under `web-components/`; the files staged below `client/Sources/Resources/` are package inputs generated from that source. Never hand-edit a staged JavaScript or CSS bundle as the implementation of a feature.

The canonical builders are:

- `scripts/build-agent-task-assets.sh` builds and stages Agent Task, scheduled-run, model-download, power-user-guide, setup-resume, Meeting Detection, ambient-suggestions, Basil Board/conversation, Meeting Assistant/analysis, Assistant Session/history, Transcription/audio-file, and Agent Task capture-input bundles.
- `scripts/build-setup-assistant-assets.sh` builds and stages Setup Assistant.
- `scripts/build-profile-editor-assets.sh` builds and stages profile, memory, and skills editing.
- `scripts/build-settings-appearance-assets.sh` builds and stages the Settings renderer.
- `scripts/build-skill-reconciliation-workspace-assets.sh` builds and stages the Skill Reconciliation Workspace.

Each builder produces Vite output and stages it under `client/Sources/Resources/` for the Swift package. The builders fail when their expected HTML or JavaScript output is missing so that an old bundle is not silently packaged. A successful package-local Vite build does not update the bundle in the native application; run the corresponding canonical builder when you need the package resource to change.

The main development launcher invokes all canonical builders. A focused builder is appropriate only when you know the affected renderer and need to update its staged resource without replacing the entire development session.

Hover help in every embedded renderer comes from `installBasilTooltips()` in `web-components/shared/tooltip/basilTooltip.ts`, which each entry calls next to `enableBackdropSurfaceFinish()`. It replaces native `title` tooltips with one styled tooltip that appears after a half-second hover or keyboard focus. Use `title` for a short hint that adds information the control does not already show; a `title` that repeats fully visible text appears only when that text is truncated. Use `data-tooltip` for multi-line text, `data-tooltip-when="truncated"` for text that should appear only when clipped, and `data-tooltip-placement` (`above`, `below`, `left`, or `right`) when the default placement below the target would cover related content. Window controls (close, minimize, collapse, expand, dismiss) carry an `aria-label` and no tooltip.

## Validation

Run the narrowest relevant checks before broad checks. These commands are repository-supported validation entry points:

```bash
poetry run pytest
swift test --package-path client
swift build --package-path client
```

For an embedded web package, run its package-local checks. For example:

```bash
cd web-components/SettingsWebComponents
npm run typecheck
npm test
npm run build
```

`npm run typecheck` runs `tsc --noEmit` against the package's `tsconfig.json`, including every `web-components/shared` file the package imports. Vitest and Vite do not type-check, so run it alongside the tests; CI runs it for every package.

`python3 scripts/check_literal_structural_colors.py` fails when web-component CSS outside a `theme.css` file uses a hardcoded black or white value that is not an accepted exception. Each exception in `scripts/literal_structural_colors_allowlist.json` is named by its file, selector, property, and value and carries a reason, so moving or editing unrelated rules does not affect it. Add a new intentional exception with `python3 scripts/check_literal_structural_colors.py --update-baseline --reason "Why it is intentional."`. CI runs the check.

Use the appropriate canonical builder after changes that must reach a packaged WebKit resource. Do not assume a package-local Vite build alone updates the client resource bundle. Builders and package builds can modify generated output, so review `git status` afterward and do not add generated assets to source control.

The repository's Python configuration is in `pyproject.toml`; the client package is in `client/Package.swift`. Follow existing component-specific tests and project guidance in `DEVELOPMENT_PRINCIPLES.md`. Before changing user-visible workflows, validate the smallest safe functional path in addition to unit/build checks.

For a native feature, use macOS Accessibility to inspect named UI elements and make a narrow functional assertion. For a browser-accessible renderer, use the browser surface to prove the relevant event and rendered state. Do not create recordings, start an agent task, approve an action, or contact an external service as a validation fixture without explicit authorization and an isolated test context.

## Working with generated and local data

Generated web bundles, application bundles, model weights, local databases, logs, and package-manager output are intentionally excluded from version control. The source-to-staging relationship and the current generated-file inventory are documented in [Generated files](generated-files.md).

Keep provider keys, signing identities, tokens, local release exports, recordings, and other private data out of the working tree. Use the configured local storage roots described in [Privacy and data flow](privacy-and-data-flow.md) when you need to inspect or remove application data; trace the owning subsystem rather than treating a broad filesystem search as authoritative.

## Packaging and release boundaries

Community builds use an ad-hoc package path:

```bash
build/scripts/build_app.sh --ad-hoc
```

The `release.sh` wrapper delegates to `build/scripts/build_app.sh`. Signing, notarization, update-feed generation, DMG publication, uploads, and release credentials are release-owner operations. They can change external systems or publish artifacts and are not routine local validation steps.

An ad-hoc community package is useful for local packaging validation. It is not a substitute for an official signed or notarized build, and it does not authorize publication. Do not use a release command with notarization or upload options unless the release owner has explicitly authorized that specific external action.

The `release-build` job in `.github/workflows/validate.yml` runs only on pushes to `main`, after the backend, web-component, and client jobs pass. It reads its signing and notarization credentials from the protected `release-build` GitHub environment, which is restricted to `main`, so pull requests never receive them. The job stamps the commit into the app's `BasilSourceCommit` Info.plist key, checks that every bundled binary resolves its libraries inside the app with `build/scripts/verify_bundle_self_contained.sh`, checks the signed DMG with `build/scripts/verify_release_artifact.sh`, attests the DMG, and replaces the `main-latest` pre-release. Repository builds never include a Sparkle update feed. [Verifying repository builds](verifying-builds.md) is the user-facing description.

[CHANGELOG.md](../CHANGELOG.md) is the single source of release notes. Add a plain-language `- ` bullet under `## Unreleased` with any user-facing change; those bullets appear in the `main-latest` notes as changes since the last website release. A website release build for version `X.Y.Z` reads the `## X.Y.Z` section through `build/scripts/changelog_section.sh` and stops before building if that section is missing, has no bullets, or contains `<` or `&`, which would break the HTML update notes. Before that build, rename `## Unreleased` to the version and add a fresh `## Unreleased` above it. Setting `BASIL_RELEASE_NOTES_FILE` overrides the changelog with a plain-text file in the same one-bullet-per-line format.

Do not add signing identities, provider credentials, tokens, local release exports, model weights, recordings, or generated artifacts to version control.

## Contribution, support, and security

- [CONTRIBUTING.md](../CONTRIBUTING.md) defines contribution requirements and the Developer Certificate of Origin.
- [DEVELOPMENT_PRINCIPLES.md](../DEVELOPMENT_PRINCIPLES.md) defines project-specific engineering guidance.
- [SUPPORT.md](../SUPPORT.md) describes public support requests and safe diagnostic information.
- [SECURITY.md](../SECURITY.md) defines the security-reporting boundary. Do not file vulnerabilities, credentials, private recordings, or personal data in public issues.
