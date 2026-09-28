# Repository layout

This repository contains the source and build inputs for the supported macOS application. It intentionally does not represent Docker, Linux, Windows, or mobile distribution as a supported public product surface.

## Primary source surfaces

- `client/` is the Swift package for the native Basil client. It contains native application lifecycle and presentation code, menu and permission integrations, audio and screen capture, WebKit hosts, packaged resources, and client-side tests.
- `backend/` is the local Python/FastAPI service. Its source contains route registration, domain services, model orchestration, persistence-facing code, WebSocket coordination, configuration, and backend tests.
- `web-components/` contains the React/Vite source for embedded interactive surfaces. Packages are grouped by shipped surface, such as the Basil Board, Meeting Assistant, Assistant Session, transcription, Settings, onboarding, Setup Assistant, and skill reconciliation.
- `scripts/` contains canonical asset builders, generators, and supporting validation utilities shared across source surfaces.
- `build/` contains local packaging inputs, third-party build helpers, and release tooling. Its scripts can create local packages and, when explicitly invoked with the appropriate options and credentials, perform owner-only release operations.

All source and build inputs use these directories. Compatibility aliases are not part of the repository.

## Source, staged resources, and build output

Web component source lives in `web-components/`, not in the corresponding Swift resource directory. A canonical script builds each renderer and stages its generated output under `client/Sources/Resources/`, where the Swift package can include it in an application bundle. The staged output is a package input, but the web component source remains authoritative.

`dev.sh` coordinates the complete local development launch and calls the canonical builders. For a narrow WebKit change, use the relevant builder in `scripts/`; see [Generated files](generated-files.md) for the builder inventory and the rule that generated output must not be committed.

## Documentation and repository policies

The root `README.md` is the GitHub cover sheet and documentation entry point. The focused guides are:

- `docs/getting-started.md` for prerequisites, local launch, and first-run permissions.
- `docs/capabilities.md` for the user-facing capability catalog, persistence, dependencies, and limitations.
- `docs/configuration.md` for Settings, models, providers, connections, permissions, and runtime controls.
- `docs/privacy-and-data-flow.md` for application data paths and external request boundaries.
- `docs/development.md` for architecture, builders, validation, and release boundaries.
- `docs/generated-files.md` for source versus generated/staged artifacts.

`CONTRIBUTING.md`, `DEVELOPMENT_PRINCIPLES.md`, `SECURITY.md`, `SUPPORT.md`, `LICENSE`, and `TRADEMARK.md` define contribution, engineering, reporting, legal, and product-identity boundaries. Read the policy document that applies rather than copying its requirements into a feature-specific change.

## Local-only and excluded material

The `local/` directory holds owner-local material and is not a public source surface. Model weights, local databases, logs, Python/Swift/Node build output, package-manager caches, packaged application bundles, and generated web JavaScript/CSS are intentionally excluded.

The backend can obtain configured models at runtime, but no model weight is a repository source file. Do not add provider keys, signing identities, release exports, recordings, or local application data to version control.
