# doingapp

A fast CLI task tracker — track what you're doing from the terminal.

```
$ doing add "Write CLI docs"
● Added: Write CLI docs  (#42)

$ doing
  ● #42  Write CLI docs
  ● #41  Review PR

$ doing done 42
✓ Done: Write CLI docs
```

## Install

```bash
pipx install doingapp
```

Or with pip:

```bash
pip install doingapp
```

Requires Python 3.11+.

## Getting started

```bash
doing login          # Log in with your Doing account
doing add "My task"  # Add a task
doing                # See what's on your plate
doing done 1         # Mark task #1 as done
```

Or authenticate with an API key (get one from the web UI at Settings → API Keys):

```bash
doing apikey --key doing_xxxxx
```

## Commands

| Command | Description |
|---------|-------------|
| `doing` | Show active tasks (same as `doing ls`) |
| `doing add <title>` | Add a task (`-n` notes, `-c` context ID) |
| `doing get <id>` | Get a single task by ID |
| `doing done <id>` | Mark a task as done |
| `doing pause <id>` | Pause a task |
| `doing resume <id>` | Resume a paused task |
| `doing reopen <id>` | Reopen a completed task |
| `doing edit <id>` | Edit a task (`-t` title, `-n` notes, `-c` context, `--no-context`) |
| `doing rm <id>` | Delete a task |
| `doing ls` | List active tasks (`-c` context ID) |
| `doing log` | Show tasks done today (`-d YYYY-MM-DD`, `-c` context ID) |
| `doing today` | Show all tasks grouped by status (`-c` context ID) |
| `doing clear` | Mark all active tasks as done |
| `doing contexts` | List contexts |
| `doing context add <name>` | Create a context |
| `doing context rm <id>` | Delete a context |
| `doing me` | Show current user info |
| `doing login` | Log in |
| `doing logout` | Log out |
| `doing apikey` | Save an API key (`-k` key) |

## JSON output

Every command supports `--json` (or `-j`) for machine-readable output. This is useful for scripting and AI coding agents like Claude Code or Codex CLI.

```bash
doing --json ls                  # [{"id": 1, "title": "...", ...}]
doing --json add "New task"      # {"id": 2, "title": "New task", ...}
doing --json done 2              # {"id": 2, "status": "done", ...}
doing --json contexts            # [{"id": 1, "name": "Work", ...}]
doing --json get 2               # {"id": 2, "title": "...", ...}
doing --json me                  # {"id": 1, "email": "...", ...}
```

Errors also return structured JSON with a non-zero exit code:

```bash
doing --json done 99999          # {"error": true, "status": 404, "detail": "Task not found"}
```

## Configuration

By default the CLI talks to `https://doingapp.co`. To point at a different server:

```bash
export DOING_API_URL=http://localhost:8001
```

## License

MIT
