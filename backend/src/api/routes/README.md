# Route Package Conventions

`api.routes` is the HTTP/WebSocket boundary for the backend. Route modules
should translate requests and responses, then delegate reusable behavior to
services or core modules.

## Domain Packages

Use a package entrypoint when a route domain has multiple modules:

- `api.routes.agent_tasks`
- `api.routes.model_routes`
- `api.routes.connections`
- `api.routes.voice_listener_routes`

The package `__init__.py` should export the router objects that `registry.py`
needs. Callers should import those package exports instead of internal route
modules.

## Standalone Routers

Keep a router as a top-level module when it is small, cohesive, and has no clear
domain package. Do not create packages just to make the folder flatter.

## Non-Route Helpers

Backend services should not import route modules for reusable helper behavior.
Move shared persistence, WebSocket bridge, token bridge, and service access
helpers into `api.services` or `api.core`, then have routes and services import
from that non-route module.

## Registration

`api.routes.registry` owns application router registration and ordering. Route
order is observable for overlapping static/dynamic paths, so changes to
registration order should be validated with route inventory checks.
