# Repository layout

`backend/` contains the Python/FastAPI application source. `client/` contains the macOS Swift package. `web-components/` contains the React/Vite applications embedded in the client. `build/` contains local packaging and release tooling. `scripts/` contains cross-component generators and validation utilities.

All source and build inputs use only `backend/`, `client/`, `web-components/`, `build/`, and `scripts/`. Compatibility aliases are not part of this repository.

Model weights, local databases, logs, Python/Swift/Node build output, package-manager caches, packaged application bundles, and generated web JavaScript/CSS are intentionally excluded. The backend can obtain configured models at runtime; no model weight is a repository source file.
