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
| `doing add <title>` | Add a task (`-x` next action, `-n` notes, `-c` context ID, `-d "tomorrow 3pm"` due, `-r daily` repeat) |
| `doing get <id>` | Get a single task by ID |
| `doing done <id>` | Mark a task as done |
| `doing touch <id>...` | Reset a task's staleness timer and move it to the top |
| `doing pause <id>` | Pause a task |
| `doing resume <id>` | Resume a paused task |
| `doing reopen <id>` | Reopen a completed task |
| `doing edit <id>` | Edit a task (`-t` title, `-x` next action, `--no-next`, `-n` notes, `-c` context, `--no-context`, `-d` due, `--no-due`, `-r` repeat, `--no-repeat`) |
| `doing snooze <id> [10m\|1h\|3h\|1d\|morning]` | Push a due task back (default 10m) |
| `doing rm <id>` | Delete a task |
| `doing ls` | List active tasks, grouped by due date (`-c` context ID, `-n` show notes) |
| `doing log` | Show tasks done today (`-d YYYY-MM-DD`, `-c` context ID) |
| `doing today` | Show all tasks grouped by status (`-c` context ID, `-n` show notes) |
| `doing clear` | Mark all active tasks as done |
| `doing contexts` | List contexts |
| `doing context add <name>` | Create a context |
| `doing context rm <id>` | Delete a context |
| `doing me` | Show current user info |
| `doing login` | Log in |
| `doing logout` | Log out |
| `doing apikey` | Save an API key (`-k` key) |

## Next actions and notes

Every task can have a **next action**: one short, concrete thing to do next. It always shows under the task in the list. Notes hold the background and stay hidden unless you ask for them (`doing ls -n`, or `doing get <id>`).

```bash
doing add "Send Q4 estimated tax" -x "Pay \$4,200 in EFTPS" -n "Amount is from the tax sheet, row 14"
doing edit 341 -x "Save the confirmation PDF"
doing edit 341 --no-next
```

**For AI agents:** whenever you add or change notes, also set `--next` to a short next action in the imperative, under 80 characters (for example `--next "Email Dana the revised quote"`). When you finish it, replace it with the one after it.

Active tasks are listed in groups: Overdue, Today, No due date, Tomorrow, Next 7 days, Future.

## Due dates and reminders

Give a task a due date and the Doing iOS app nags you every few minutes once it's overdue, until you mark it done or snooze it.

```bash
doing add "Call mom" -d "tomorrow 3pm"
doing add "Water plants" -d friday -r 3d      # repeats 3 days after each completion
doing add "Standup notes" -d "9am" -r weekdays
doing add "Pay rent" -d "dec 1" -r monthly
doing add "Board meeting" -d "nov 10 9am" -r monthly:2tue
doing snooze 12 1h
```

`-d` accepts natural language: `in 20m`, `tonight`, `fri 9am`, `oct 30`. Dates without a time use your morning time (9:00 by default). `-r` accepts `daily`, `weekdays`, days like `mon,thu`, `Nd` (N days after done), or monthly rules:

| `-r` | Repeats |
|------|---------|
| `monthly` | same day each month as the due date |
| `quarterly`, `yearly`, `6mo` | every 3, 12, or 6 months, same day |
| `monthly:15` | the 15th (a 31st clamps to the end of short months) |
| `monthly:last` | the last day of the month |
| `monthly:2tue` | the 2nd Tuesday |
| `monthly:lastfri` | the last Friday |
| `monthly:15/3` | the 15th, every 3 months |

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
