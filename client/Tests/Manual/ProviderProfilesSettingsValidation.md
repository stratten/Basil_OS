# Manual verification: Provider Profiles settings sub-tab (Package 5C.1)

Automated coverage proves the backend inventory/validation logic and the Swift DTO decoding contract. This checklist proves the actual rendered SwiftUI sub-tab, which has no automated UI-test harness in this repository.

## Setup

1. Build and run BasilClient locally with the backend running.
2. Open Settings > Connections.

## Steps

1. Confirm a segmented "Servers" / "Provider Profiles" picker now appears above the existing connected-servers list, and that "Servers" is selected by default and renders exactly as before this package (no visual regression to the MCP connections list or call log).
2. Select "Provider Profiles" with zero profiles seeded in the database. Confirm the empty-state message renders ("No provider profiles yet...") and no error banner appears.
3. Using the Python REPL or `sqlite3` CLI against the local Basil database, call `provider_run_repository.create_profile(display_name="Test Provider", launch_argv=("echo", "hi"))` (or an equivalent one-off script) to seed one well-formed enabled profile with no workspace grant. Reload the tab (switch to Servers and back, or relaunch). Confirm the profile row appears with a green "Enabled" status dot, an "Unverified" capability badge, and "No active workspace grant."
4. Call `provider_run_repository.grant_workspace(...)` for that profile with a real local directory. Reload. Confirm the granted directory path now appears under the profile row.
5. Call `provider_run_repository.set_profile_status(profile_id, "disabled")`. Reload. Confirm the row now shows a gray "Disabled" status dot and no validation error.
6. Directly update that profile's row via `sqlite3` (`UPDATE provider_profiles SET launch_argv_json = '[]' WHERE id = ...`) to simulate a structurally invalid profile, and re-enable it via `set_profile_status(profile_id, "enabled")`. Reload. Confirm the row shows an orange "Enabled, invalid" status dot and a red sanitized validation message mentioning `launch_argv`.
7. Call `provider_run_repository.set_profile_status(profile_id, "removed")`. Reload. Confirm the profile disappears from the list, and separately confirm via `sqlite3` that its row still exists in `provider_profiles` with `status = 'removed'` (nothing was deleted).
8. Confirm at every step above that no button, menu, or control anywhere in the Provider Profiles sub-tab creates, edits, enables/disables, removes, or launches a profile — the only available action is switching sub-tabs.
