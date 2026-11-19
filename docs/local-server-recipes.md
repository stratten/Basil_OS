# Local server recipes

A local server is a program on your Mac that Basil starts and talks to. Some programs need more than a command: a tool installed first, a file downloaded or built, and a background program that has to be running, and sometimes waiting for you, before the server works. A recipe tells Basil all of that, so Basil can do the work and watch it. Basil's own code names no particular program. The recipe comes from Settings (Add Connection, then A program on this Mac, then Paste a setup recipe) or from the agent, and nothing runs until you approve a card that lists exactly what the recipe will do.

## The two parts

A recipe has an `install` part, which says what must be in place, and a `probe` part, which says how to tell whether the background program is ready. Either can be used alone. The `probe` belongs to the background program, so it goes inside `companion` when the agent registers a server, and beside `install` in the pasted JSON.

```json
{
  "install": {
    "requirements": [
      {"name": "Go", "reason": "It builds the bridge.", "check": ["go", "version"], "install": ["brew", "install", "go"], "for_method": "build"}
    ],
    "artifacts": [
      {
        "name": "Bridge",
        "expects": "bin/bridge",
        "methods": [
          {"kind": "download", "url": "https://example.com/releases/bridge-{os}-{arch}", "sha256_by_arch": {"arm64": "64 hex characters", "amd64": "64 hex characters"}},
          {"kind": "build", "git_url": "https://example.com/org/bridge.git", "commit": "the full 40-character commit", "steps": [{"argv": ["go", "build", "-o", "{install_dir}/bin/bridge", "."], "cwd": "cmd"}]}
        ]
      }
    ]
  },
  "probe": {
    "url": "http://127.0.0.1:{port}/status",
    "auth": "none",
    "state_path": "state",
    "states": {"connected": "ready", "waiting": "needs_action", "starting": "starting", "error": "failed"},
    "message_path": "message",
    "action_kind": "qr",
    "action_path": "code",
    "expires_path": "expires_at"
  }
}
```

## Requirements

A requirement names a program the recipe needs. `check` is an argument list Basil runs to see whether it is already there. `install` is optional: when present, the Install button in Settings, or an approval card from the agent, offers to run exactly that command, and each requirement is approved on its own. Without `install`, Basil tells you to install it yourself. `for_method` says when the requirement matters: `any` is checked first, `download` or `build` only when Basil is about to use a method of that kind. Building also needs `git`, which Basil checks for itself.

## Artifacts and methods

An artifact is a file Basil must have. `expects` is where it ends up, relative to the connection's own folder, which `{install_dir}` stands for. Methods are tried in the order listed, and a method that fails for any reason except a mismatch falls back to the next one.

A `download` method needs an `https` address with no embedded credentials, and a `sha256`, or `sha256_by_arch` with `arm64` and `amd64` keys. The address may use `{os}` and `{arch}`. If the file is an archive, give `archive` as `tar.gz` or `zip`, and optionally `strip_components`. A file whose SHA-256 does not match is deleted and never run, and Basil does not fall back to another method after a mismatch.

A `build` method needs an `https` git address, the full 40-character `commit`, and `steps`, each an argument list with an optional relative `cwd`. Basil fetches exactly that commit, refuses anything else, runs the steps, and confirms the expected file exists. A commit that does not match also stops the whole artifact.

Every command is an argument list and runs without a shell, in a cleaned environment, with a time limit. Archives that try to write outside their folder, such as absolute paths, `..`, or links that point outside, are refused.

## Placeholders

| Placeholder | Meaning | Where it can be used |
| --- | --- | --- |
| `{install_dir}` | The connection's private folder for files the recipe puts in place | Commands, arguments, folders, settings, build steps |
| `{data_dir}` | A folder the program may keep its own data in | Commands, arguments, folders, settings, build steps |
| `{port}` | A free port Basil picks for the background program | The server and background program definitions, and the probe address |
| `{run_secret}` | A fresh token Basil generates every time the background program starts, held in memory only | The background program only |
| `{os}`, `{arch}` | `darwin`, and `arm64` or `amd64` | Download addresses only |

## The probe

The probe is how Basil reads the background program's own status page. The `url` must be an `http` or `https` address on this Mac (`127.0.0.1`, `localhost` or `::1`) with no embedded credentials, and it must contain `{port}`. `auth` is `none`, `bearer_run_secret` (the generated token), or `bearer_secret` with a `secret_name` you saved in your Keychain. `state_path` is a dotted path to a value in the page's JSON, and `states` maps each value to `starting`, `ready`, `needs_action`, or `failed`. Optional `message_path` names a sentence to show. For a code to scan, `action_kind` is `qr`, `action_path` is where the code text is, and `expires_path` is when it stops being valid. Basil does not follow redirects, reads the page every `interval_seconds` (optional, 1 to 30, default 3), and treats three failed reads in a row as a problem.

The code text is held in memory, drawn only in Settings, and never saved, logged, shown to the agent, or sent to a model provider.

## What Basil does with a recipe

Registering a recipe saves the definition and shows the approval card. It does not download or run anything. In Settings the row then shows Setup, with every program and file and the exact commands, and a Prepare button. Choosing Prepare, or approving the agent's registration, starts the work in the background. Basil checks requirements, downloads or builds each file, verifies it, and then starts the background program, so any step that needs you appears in the row. Progress survives a restart: a file that is already in place and matches the recipe is not fetched again. The agent can follow along with the catalog action `local_server_status`, and can correct a recipe that failed by registering again with `replace` set to that connection's id, which rewrites the server in place and keeps its saved secret values.

## What is not covered

Basil does not sign or notarize anyone's program. A binary Basil downloads carries no quarantine mark, and a Go build on Apple silicon is signed ad hoc by the toolchain, so macOS runs both. You are trusting the source and the SHA-256 or commit in the recipe, which is why the approval card shows them in full.
