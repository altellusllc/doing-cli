import json
import re
import sys
from datetime import datetime, timezone

import httpx
import typer
from rich.console import Console
from rich.markup import escape

from doing_cli import api
from doing_cli.auth import load_token, save_token, clear_token

app = typer.Typer(
    help="Doing - track what you're working on.",
    invoke_without_command=True,
)
context_app = typer.Typer(help="Manage contexts.")
app.add_typer(context_app, name="context")

console = Console()

# Commands that don't require authentication
AUTH_COMMANDS = {"login", "register", "logout", "apikey"}

# Global JSON mode flag, set by --json on any command
_json_mode = False


def _output_json(data) -> None:
    """Write raw JSON to stdout (no Rich formatting) and exit."""
    sys.stdout.write(json.dumps(data) + "\n")
    raise typer.Exit()


def _require_auth():
    """Exit with a message if the user is not logged in."""
    if load_token() is None:
        if _json_mode:
            _output_json({"error": True, "detail": "Not logged in"})
        console.print("[bold red]Not logged in.[/bold red] Run: [bold]doing login[/bold]")
        raise typer.Exit(code=1)


def _error_detail(response: httpx.Response) -> str:
    """The API's human-readable message, including FastAPI's 422 validation format."""
    try:
        detail = response.json().get("detail", response.text)
    except Exception:
        return response.text
    if isinstance(detail, list):
        return "; ".join(str(d.get("msg", d)).removeprefix("Value error, ") for d in detail)
    return str(detail)


def _handle_api_error(exc: Exception):
    if _json_mode:
        error: dict = {"error": True}
        if isinstance(exc, httpx.HTTPStatusError):
            error["status"] = exc.response.status_code
            try:
                error["detail"] = exc.response.json().get("detail", exc.response.text)
            except Exception:
                error["detail"] = exc.response.text
        elif isinstance(exc, (httpx.ConnectError, httpx.TimeoutException)):
            error["detail"] = f"Could not connect to {api.BASE_URL}"
        else:
            error["detail"] = str(exc)
        sys.stdout.write(json.dumps(error) + "\n")
        raise typer.Exit(code=1)

    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status == 401:
            console.print(
                "[bold red]Session expired or invalid.[/bold red] Run: [bold]doing login[/bold]"
            )
        elif status == 404:
            console.print("[bold red]Not found.[/bold red]")
        else:
            console.print(f"[bold red]API error ({status}):[/bold red] {escape(_error_detail(exc.response))}")
    elif isinstance(exc, (httpx.ConnectError, httpx.TimeoutException)):
        console.print(
            f"[bold red]Could not connect to the Doing API at {api.BASE_URL}[/bold red]\n"
            "Make sure the backend is running."
        )
    else:
        console.print(f"[bold red]Unexpected error:[/bold red] {exc}")
    raise typer.Exit(code=1)


def _validation_error(detail: str):
    """Print a validation error (JSON or Rich) and exit with code 1."""
    if _json_mode:
        _output_json({"error": True, "detail": detail})
    console.print(f"[bold red]{escape(detail)}[/bold red]")
    raise typer.Exit(code=1)


def _validate_title(title: str) -> str:
    """Strip whitespace and newlines from title, validate non-empty."""
    cleaned = title.replace("\n", " ").replace("\r", " ").strip()
    if not cleaned:
        _validation_error("Title cannot be empty")
    return cleaned


def _validate_name(name: str) -> str:
    """Strip and validate non-empty name for contexts."""
    cleaned = name.strip()
    if not cleaned:
        _validation_error("Name cannot be empty")
    return cleaned


WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


REPEAT_HELP = (
    "daily, weekdays, mon,thu, 3d (3 days after done), monthly, quarterly, yearly, "
    "3mo, or monthly:15 / monthly:last / monthly:2tue / monthly:lastfri (add /3 for every 3 months)"
)


def _normalize_repeat(value: str) -> str:
    """Accept friendly repeat specs and turn them into the API's rule format.

    Monthly shorthands without a day ("monthly", "quarterly", "3mo") are sent
    without an anchor; the server takes the day from the task's due date.
    """
    v = value.strip().lower().replace(" ", "")
    if v in ("daily", "weekdays") or v.startswith(("weekly:", "after:", "monthly")):
        return v
    if v == "quarterly":
        return "monthly/3"
    if v in ("yearly", "annually"):
        return "monthly/12"
    if m := re.fullmatch(r"(\d+)(mo|months?)", v):
        return "monthly" if m.group(1) == "1" else f"monthly/{m.group(1)}"
    if all(day in WEEKDAYS for day in v.split(",")):
        return f"weekly:{v}"
    if m := re.fullmatch(r"(\d+)d(ays?)?", v):
        return f"after:{m.group(1)}"
    _validation_error(f"Invalid --repeat '{value}'. Use {REPEAT_HELP}.")


def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _describe_monthly(rule: str) -> str:
    body = rule.split(":", 1)[1] if ":" in rule else rule
    anchor, _, every = body.partition("/")
    if anchor == "last":
        day = "the last day"
    elif anchor.isdigit():
        day = f"the {_ordinal(int(anchor))}"
    elif anchor.startswith("last"):
        day = f"the last {anchor[4:].title()}"
    else:
        day = f"the {_ordinal(int(anchor[0]))} {anchor[1:].title()}"
    n = int(every or 1)
    period = {1: "monthly", 3: "quarterly", 12: "yearly"}.get(n, f"every {n} months")
    return f"{period} on {day}"


def _describe_repeat(rule: str) -> str:
    if rule.startswith("weekly:"):
        return "every " + ", ".join(d.title() for d in rule.split(":", 1)[1].split(","))
    if rule.startswith("after:"):
        n = rule.split(":", 1)[1]
        return f"{n} day{'s' if n != '1' else ''} after done"
    if rule.startswith("monthly:"):
        return _describe_monthly(rule)
    return rule


def _local_due(task: dict) -> datetime | None:
    if not task.get("due_at"):
        return None
    due = datetime.fromisoformat(task["due_at"])
    if due.tzinfo is None:
        due = due.replace(tzinfo=timezone.utc)
    return due.astimezone()


def _format_due(task: dict) -> str:
    """Rich-formatted due label, e.g. '[red]overdue · Mon 3:00 PM[/red]'."""
    due = _local_due(task)
    if due is None:
        return ""
    now = datetime.now().astimezone()
    if task.get("due_all_day"):
        when = due.strftime("%a %b %-d")
    elif due.date() == now.date():
        when = due.strftime("%-I:%M %p")
    else:
        when = due.strftime("%a %b %-d %-I:%M %p")
    repeat = f" ↻ {_describe_repeat(task['recurrence'])}" if task.get("recurrence") else ""
    if task.get("status") == "active" and due <= now:
        return f"  [bold red]⏰ overdue · {when}{repeat}[/bold red]"
    return f"  [cyan]⏰ {when}{repeat}[/cyan]"


def _print_notes(task: dict, show_notes: bool = True) -> None:
    """Print the next action (always) and the notes (only when asked).

    Hidden notes leave a '+note' marker so you know there's more to see.
    """
    marker = "  [dim]+note[/dim]" if task.get("notes") and not show_notes else ""
    if task.get("next_action"):
        console.print(f"       [green]→ {escape(task['next_action'])}[/green]{marker}")
    elif marker:
        console.print(f"     {marker}")
    if show_notes and task.get("notes"):
        console.print(f"       [dim]{task['notes']}[/dim]")


def _print_active_task(task: dict, show_notes: bool = True) -> None:
    ctx = f"  [dim][{task['context_name']}][/dim]" if task.get("context_name") else ""
    console.print(f"  [green bold]●[/green bold] [dim]#{task['id']}[/dim]  {task['title']}{ctx}{_format_due(task)}")
    _print_notes(task, show_notes)


def _print_paused_task(task: dict, show_notes: bool = True) -> None:
    ctx = f"  [dim][{task['context_name']}][/dim]" if task.get("context_name") else ""
    console.print(f"  [yellow]⏸[/yellow] [dim]#{task['id']}[/dim]  {task['title']}{ctx}{_format_due(task)}")
    _print_notes(task, show_notes)


def _print_done_task(task: dict, show_notes: bool = True) -> None:
    ctx = f"  [{task['context_name']}]" if task.get("context_name") else ""
    console.print(f"  [green]✓[/green] [dim]#{task['id']}  [strike]{task['title']}[/strike]{ctx}[/dim]")
    _print_notes(task, show_notes)


DUE_GROUPS = [
    ("overdue", "[bold red]Overdue[/bold red]"),
    ("today", "[bold]Today[/bold]"),
    ("none", "[bold]No due date[/bold]"),
    ("tomorrow", "[bold]Tomorrow[/bold]"),
    ("week", "[bold]Next 7 days[/bold]"),
    ("future", "[bold]Future[/bold]"),
]


def _due_group(task: dict, now: datetime) -> str:
    due = _local_due(task)
    if due is None:
        return "none"
    if due <= now:
        return "overdue"
    days = (due.date() - now.date()).days
    if days == 0:
        return "today"
    if days == 1:
        return "tomorrow"
    return "week" if days <= 7 else "future"


def _print_active_tasks(tasks: list[dict], show_notes: bool) -> None:
    """Print active tasks under due-date group headings.

    The server already returns them in group order. With no due dates at
    all, the single 'No due date' heading is noise, so skip headings.
    """
    if not any(t.get("due_at") for t in tasks):
        for t in tasks:
            _print_active_task(t, show_notes)
        return
    now = datetime.now().astimezone()
    groups: dict[str, list[dict]] = {}
    for t in tasks:
        groups.setdefault(_due_group(t, now), []).append(t)
    for key, heading in DUE_GROUPS:
        if key in groups:
            console.print(f"\n{heading} [dim]{len(groups[key])}[/dim]")
            for t in groups[key]:
                _print_active_task(t, show_notes)


@app.callback()
def main(
    ctx: typer.Context,
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON (for scripting and AI agents)"),
):
    """Doing - track what you're working on."""
    global _json_mode
    _json_mode = json_output
    if ctx.invoked_subcommand is None:
        _require_auth()
        ls()
    elif ctx.invoked_subcommand not in AUTH_COMMANDS:
        _require_auth()


@app.command()
def login():
    """Log in to your Doing account."""
    email = typer.prompt("Email")
    password = typer.prompt("Password", hide_input=True)
    try:
        data = api.login(email, password)
    except Exception as exc:
        _handle_api_error(exc)
    save_token(data["access_token"])
    if _json_mode:
        _output_json({"ok": True, "email": email})
    console.print(f"[bold green]Logged in[/bold green] as [bold]{email}[/bold]")


@app.command()
def register(
    token: str = typer.Argument(..., help="Invite token from your invitation link"),
):
    """Create a new Doing account using an invite token."""
    password = typer.prompt("Password", hide_input=True)
    password_confirm = typer.prompt("Confirm password", hide_input=True)
    if password != password_confirm:
        if _json_mode:
            _output_json({"error": True, "detail": "Passwords do not match"})
        console.print("[bold red]Passwords do not match.[/bold red]")
        raise typer.Exit(code=1)
    try:
        data = api.register(token, password)
    except Exception as exc:
        _handle_api_error(exc)
    save_token(data["access_token"])
    if _json_mode:
        _output_json({"ok": True})
    console.print("[bold green]Account created![/bold green] You're now logged in.")


@app.command()
def logout():
    """Log out and clear stored credentials."""
    clear_token()
    if _json_mode:
        _output_json({"ok": True})
    console.print("[dim]Logged out.[/dim]")


@app.command()
def apikey(
    key: str = typer.Option(None, "--key", "-k", help="API key (starts with doing_)"),
):
    """Save an API key for authentication (get one from the web UI)."""
    if key is None:
        key = typer.prompt("API key", hide_input=True)
    if not key.startswith("doing_"):
        if _json_mode:
            _output_json({"error": True, "detail": "Invalid API key. Keys start with doing_"})
        console.print("[bold red]Invalid API key.[/bold red] Keys start with [bold]doing_[/bold]")
        raise typer.Exit(code=1)
    save_token(key)
    if _json_mode:
        _output_json({"ok": True})
    console.print("[bold green]API key saved.[/bold green] You're all set.")


@app.command()
def me():
    """Show current user info (useful for verifying auth)."""
    try:
        user = api.get_me()
    except Exception as exc:
        _handle_api_error(exc)
    if _json_mode:
        _output_json(user)
    console.print(f"  [bold]{user['email']}[/bold]  [dim](#{user['id']})[/dim]")
    if user.get("is_admin"):
        console.print("  [yellow]Admin[/yellow]")


@app.command()
def add(
    title: str = typer.Argument(..., help="What are you working on?"),
    notes: str = typer.Option(None, "--notes", "-n", help="Background detail. Whenever you add notes, also set --next."),
    next_action: str = typer.Option(
        None, "--next", "-x",
        help="The next concrete action, under 80 characters, e.g. 'Email Dana the revised quote'. "
             "Always set this when you add notes; it's what shows in the task list.",
    ),
    context: int = typer.Option(None, "--context", "-c", help="Context ID"),
    due: str = typer.Option(None, "--due", "-d", help="When it's due, e.g. 'tomorrow 3pm', 'in 20m', 'friday'"),
    repeat: str = typer.Option(None, "--repeat", "-r", help=REPEAT_HELP),
):
    """Add something to your plate."""
    title = _validate_title(title)
    recurrence = _normalize_repeat(repeat) if repeat else None
    try:
        task = api.create_task(title, notes, context, due=due, recurrence=recurrence,
                               next_action=next_action)
    except Exception as exc:
        _handle_api_error(exc)
    if _json_mode:
        _output_json(task)
    console.print(f"[green bold]●[/green bold] Added: [bold]{task['title']}[/bold]  [dim](#{task['id']})[/dim]{_format_due(task)}")
    _print_notes(task, show_notes=False)


@app.command()
def get(
    task_id: int = typer.Argument(..., help="ID of the task to fetch"),
):
    """Get a single task by ID."""
    try:
        task = api.get_task(task_id)
    except Exception as exc:
        _handle_api_error(exc)
    if _json_mode:
        _output_json(task)
    status_icon = {"active": "[green bold]●[/green bold]", "paused": "[yellow]⏸[/yellow]", "done": "[green]✓[/green]"}
    icon = status_icon.get(task["status"], "?")
    ctx = f"  [dim][{task['context_name']}][/dim]" if task.get("context_name") else ""
    console.print(f"  {icon} [dim]#{task['id']}[/dim]  {task['title']}{ctx}{_format_due(task)}")
    _print_notes(task)
    console.print(f"       [dim]Status: {task['status']}  Created: {task['created_at']}[/dim]")


@app.command()
def ls(
    context: int = typer.Option(None, "--context", "-c", help="Filter by context ID"),
    show_notes: bool = typer.Option(False, "--notes", "-n", help="Show notes (hidden by default)"),
):
    """Show what's on your plate right now."""
    try:
        tasks = api.list_tasks(status="active", context_id=context)
    except Exception as exc:
        _handle_api_error(exc)
    if _json_mode:
        _output_json(tasks)
    if not tasks:
        console.print("Nothing on your plate. Add something: [bold]doing add 'task name'[/bold]")
        raise typer.Exit()
    _print_active_tasks(tasks, show_notes)


@app.command()
def log(
    date: str = typer.Option(None, "--date", "-d", help="Date (YYYY-MM-DD), defaults to today"),
    context: int = typer.Option(None, "--context", "-c", help="Filter by context ID"),
):
    """List tasks marked done today (or on a given date)."""
    from datetime import date as date_cls
    query_date = date if date else date_cls.today().isoformat()
    try:
        tasks = api.list_tasks(status="done", date=query_date, context_id=context)
    except Exception as exc:
        _handle_api_error(exc)
    if _json_mode:
        _output_json(tasks)
    if not tasks:
        label = query_date if date else "today"
        console.print(f"Nothing marked done {label}.")
        raise typer.Exit()
    for t in tasks:
        _print_done_task(t)


@app.command()
def done(
    task_ids: list[int] = typer.Argument(..., help="ID(s) of the task(s) to mark done"),
):
    """Mark one or more tasks as done."""
    results = []
    errors = []
    for task_id in task_ids:
        try:
            task = api.mark_done(task_id)
        except Exception as exc:
            if _json_mode and len(task_ids) == 1:
                _handle_api_error(exc)
            if not _json_mode:
                console.print(f"[red]Failed to complete task #{task_id}[/red]")
            errors.append(task_id)
            continue
        results.append(task)
        if not _json_mode:
            next_due = f"  [dim]next:[/dim]{_format_due(task)}" if task.get("recurrence") else ""
            console.print(f"[green]✓[/green] Done: [bold]{task['title']}[/bold]{next_due}")
    if _json_mode:
        _output_json(results[0] if len(task_ids) == 1 and results else results)
    if errors:
        raise typer.Exit(code=1)


@app.command()
def touch(
    task_ids: list[int] = typer.Argument(..., help="ID(s) of the task(s) to touch"),
):
    """Mark tasks as still in progress: resets the staleness timer and moves them to the top."""
    results = []
    errors = []
    for task_id in task_ids:
        try:
            task = api.touch_task(task_id)
        except Exception as exc:
            if _json_mode and len(task_ids) == 1:
                _handle_api_error(exc)
            if not _json_mode:
                detail = ""
                if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 400:
                    detail = f": {exc.response.json().get('detail', '')}"
                console.print(f"[red]Failed to touch task #{task_id}{detail}[/red]")
            errors.append(task_id)
            continue
        results.append(task)
        if not _json_mode:
            console.print(f"[green bold]●[/green bold] Touched: [bold]{task['title']}[/bold]")
    if _json_mode:
        _output_json(results[0] if len(task_ids) == 1 and results else results)
    if errors:
        raise typer.Exit(code=1)


@app.command()
def reopen(
    task_id: int = typer.Argument(..., help="ID of the task to reopen"),
):
    """Reopen a completed task."""
    try:
        task = api.reopen_task(task_id)
    except Exception as exc:
        _handle_api_error(exc)
    if _json_mode:
        _output_json(task)
    console.print(f"[green bold]●[/green bold] Reopened: [bold]{task['title']}[/bold]")


@app.command()
def pause(
    task_id: int = typer.Argument(..., help="ID of the task to pause"),
):
    """Pause an active task."""
    try:
        task = api.pause_task(task_id)
    except Exception as exc:
        _handle_api_error(exc)
    if _json_mode:
        _output_json(task)
    console.print(f"[yellow]⏸[/yellow] Paused: [bold]{task['title']}[/bold]")


@app.command()
def resume(
    task_id: int = typer.Argument(..., help="ID of the task to resume"),
):
    """Resume a paused task."""
    try:
        task = api.resume_task(task_id)
    except Exception as exc:
        _handle_api_error(exc)
    if _json_mode:
        _output_json(task)
    console.print(f"[green bold]●[/green bold] Resumed: [bold]{task['title']}[/bold]")


@app.command()
def edit(
    task_id: int = typer.Argument(..., help="ID of the task to edit"),
    title: str = typer.Option(None, "--title", "-t", help="New title"),
    notes: str = typer.Option(None, "--notes", "-n", help="New notes. Whenever you change notes, also update --next."),
    next_action: str = typer.Option(
        None, "--next", "-x",
        help="New next action, under 80 characters. Update it whenever you change notes or finish the current one.",
    ),
    no_next: bool = typer.Option(False, "--no-next", help="Remove the next action"),
    context: int = typer.Option(None, "--context", "-c", help="Move to context ID"),
    no_context: bool = typer.Option(False, "--no-context", help="Remove context"),
    due: str = typer.Option(None, "--due", "-d", help="When it's due, e.g. 'tomorrow 3pm'"),
    no_due: bool = typer.Option(False, "--no-due", help="Remove due date (and repeat)"),
    repeat: str = typer.Option(None, "--repeat", "-r", help=REPEAT_HELP),
    no_repeat: bool = typer.Option(False, "--no-repeat", help="Stop repeating"),
):
    """Edit a task's title, notes, next action, context, due date, or repeat."""
    if no_next and next_action is not None:
        _validation_error("--no-next and --next cannot be used together")
    if no_context and context is not None:
        _validation_error("--no-context and --context cannot be used together")
    if no_due and due is not None:
        _validation_error("--no-due and --due cannot be used together")
    if no_repeat and repeat is not None:
        _validation_error("--no-repeat and --repeat cannot be used together")

    if (title is None and notes is None and next_action is None and not no_next
            and context is None and not no_context
            and due is None and not no_due and repeat is None and not no_repeat):
        _validation_error("No changes specified. Use --title, --notes, --next, --context, --due, or --repeat.")

    if title is not None:
        title = _validate_title(title)
    recurrence = _normalize_repeat(repeat) if repeat else None

    try:
        task = api.update_task(task_id, title=title, notes=notes,
                               context_id=context, clear_context=no_context,
                               due=due, clear_due=no_due,
                               recurrence=recurrence, clear_recurrence=no_repeat,
                               next_action="" if no_next else next_action)
    except Exception as exc:
        _handle_api_error(exc)
    if _json_mode:
        _output_json(task)
    console.print(f"[green bold]Updated:[/green bold] {task['title']}  [dim](#{task['id']})[/dim]{_format_due(task)}")
    _print_notes(task, show_notes=False)


@app.command()
def snooze(
    task_id: int = typer.Argument(..., help="ID of the task to snooze"),
    duration: str = typer.Argument("10m", help="10m, 1h, 3h, 1d, or 'morning' (tomorrow morning)"),
):
    """Push a task's due time back (stops the nagging until then)."""
    d = duration.strip().lower()
    minutes = preset = None
    if d in ("morning", "tomorrow"):
        preset = "tomorrow_morning"
    elif m := re.fullmatch(r"(\d+)\s*(m|min|h|hr|d)", d):
        minutes = int(m.group(1)) * {"m": 1, "min": 1, "h": 60, "hr": 60, "d": 1440}[m.group(2)]
    else:
        _validation_error(f"Invalid duration '{duration}'. Use 10m, 1h, 3h, 1d, or morning.")
    try:
        task = api.snooze_task(task_id, minutes=minutes, preset=preset)
    except Exception as exc:
        _handle_api_error(exc)
    if _json_mode:
        _output_json(task)
    console.print(f"[cyan]💤 Snoozed:[/cyan] [bold]{task['title']}[/bold]{_format_due(task)}")


@app.command()
def today(
    context: int = typer.Option(None, "--context", "-c", help="Filter by context ID"),
    show_notes: bool = typer.Option(False, "--notes", "-n", help="Show notes (hidden by default)"),
):
    """Show everything from today, grouped by status."""
    try:
        data = api.get_today(context_id=context)
    except Exception as exc:
        _handle_api_error(exc)

    if _json_mode:
        _output_json(data)

    active = data.get("active", [])
    paused = data.get("paused", [])
    done_tasks = data.get("done", [])

    if not active and not paused and not done_tasks:
        console.print("Nothing on your plate today. Add something: [bold]doing add 'task name'[/bold]")
        raise typer.Exit()

    if active:
        if not any(t.get("due_at") for t in active):
            console.print("\n[bold]Active[/bold]")
        _print_active_tasks(active, show_notes)

    if paused:
        console.print("\n[bold yellow]Paused[/bold yellow]")
        for t in paused:
            _print_paused_task(t, show_notes)

    if done_tasks:
        console.print("\n[bold]Done[/bold]")
        for t in done_tasks:
            _print_done_task(t, show_notes)

    console.print()


@app.command()
def rm(
    task_id: int = typer.Argument(..., help="ID of the task to delete"),
):
    """Delete a task."""
    try:
        api.delete_task(task_id)
    except Exception as exc:
        _handle_api_error(exc)
    if _json_mode:
        _output_json({"deleted": True, "id": task_id})
    console.print(f"[dim]Deleted task #{task_id}.[/dim]")


@app.command()
def clear():
    """Mark ALL active tasks as done."""
    try:
        tasks = api.list_tasks(status="active")
    except Exception as exc:
        _handle_api_error(exc)

    if not tasks:
        if _json_mode:
            _output_json([])
        console.print("Nothing to clear.")
        raise typer.Exit()

    results = []
    for t in tasks:
        try:
            result = api.mark_done(t["id"])
            results.append(result)
        except Exception:
            if not _json_mode:
                console.print(f"[red]Failed to complete task #{t['id']}[/red]")
            continue
        if not _json_mode:
            console.print(f"[green]✓[/green] Done: [bold]{t['title']}[/bold]")

    if _json_mode:
        _output_json(results)

    console.print(f"\n[dim]Cleared {len(tasks)} task(s).[/dim]")


@app.command()
def contexts():
    """List all contexts."""
    try:
        ctx_list = api.list_contexts()
    except Exception as exc:
        _handle_api_error(exc)
    if _json_mode:
        _output_json(ctx_list)
    if not ctx_list:
        console.print("No contexts. Create one: [bold]doing context add 'name'[/bold]")
        raise typer.Exit()
    for c in ctx_list:
        console.print(f"  [dim]#{c['id']}[/dim]  {c['name']}")


@context_app.command("add")
def context_add(
    name: str = typer.Argument(..., help="Context name"),
):
    """Create a new context."""
    name = _validate_name(name)
    try:
        ctx = api.create_context(name)
    except Exception as exc:
        _handle_api_error(exc)
    if _json_mode:
        _output_json(ctx)
    console.print(f"[green bold]Created context:[/green bold] {ctx['name']}  [dim](#{ctx['id']})[/dim]")


@context_app.command("edit")
def context_edit(
    context_id: int = typer.Argument(..., help="Context ID to edit"),
    name: str = typer.Option(None, "--name", "-n", help="New name"),
    icon: str = typer.Option(None, "--icon", "-i", help="New icon (emoji)"),
):
    """Rename a context or change its icon."""
    if name is None and icon is None:
        _validation_error("No changes specified. Use --name or --icon.")

    if name is not None:
        name = _validate_name(name)

    # Need current name if only changing icon (API requires name)
    if name is None:
        try:
            current = api.get_context(context_id)
        except Exception as exc:
            _handle_api_error(exc)
        name = current["name"]

    try:
        ctx = api.update_context(context_id, name=name, icon=icon)
    except Exception as exc:
        _handle_api_error(exc)
    if _json_mode:
        _output_json(ctx)
    console.print(f"[green bold]Updated context:[/green bold] {ctx['name']}  [dim](#{ctx['id']})[/dim]")


@context_app.command("snooze")
def context_snooze(
    context_id: int = typer.Argument(..., help="Context ID to snooze"),
):
    """Snooze a context until end of day (hides its tasks)."""
    try:
        ctx = api.snooze_context(context_id)
    except Exception as exc:
        _handle_api_error(exc)
    if _json_mode:
        _output_json(ctx)
    console.print(f"[yellow]😴 Snoozed:[/yellow] {ctx['name']} until end of day")


@context_app.command("unsnooze")
def context_unsnooze(
    context_id: int = typer.Argument(..., help="Context ID to unsnooze"),
):
    """Unsnooze a context (show its tasks again)."""
    try:
        ctx = api.unsnooze_context(context_id)
    except Exception as exc:
        _handle_api_error(exc)
    if _json_mode:
        _output_json(ctx)
    console.print(f"[green bold]Unsnoozed:[/green bold] {ctx['name']}")


@context_app.command("rm")
def context_rm(
    context_id: int = typer.Argument(..., help="Context ID to delete"),
):
    """Delete a context (tasks keep their data, just lose the context)."""
    try:
        api.delete_context(context_id)
    except Exception as exc:
        _handle_api_error(exc)
    if _json_mode:
        _output_json({"deleted": True, "id": context_id})
    console.print(f"[dim]Deleted context #{context_id}.[/dim]")


@app.command()
def stats(
    context: int = typer.Option(None, "--context", "-c", help="Filter by context ID"),
):
    """Show how many tasks you've completed today and this week."""
    try:
        data = api.get_stats(context_id=context)
    except Exception as exc:
        _handle_api_error(exc)

    if _json_mode:
        _output_json(data)

    today_count = data["today"]
    week_count = data["this_week"]
    total_count = data["total"]

    console.print(f"\n  [bold]Today:[/bold]     {today_count} task{'s' if today_count != 1 else ''} done")
    console.print(f"  [bold]This week:[/bold] {week_count} task{'s' if week_count != 1 else ''} done")

    if total_count > week_count:
        console.print(f"  [dim]All time: {total_count} total[/dim]")
    console.print()


if __name__ == "__main__":
    app()
