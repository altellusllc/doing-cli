import json
import sys

import httpx
import typer
from rich.console import Console

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
            console.print(f"[bold red]API error ({status}):[/bold red] {exc.response.text}")
    elif isinstance(exc, (httpx.ConnectError, httpx.TimeoutException)):
        console.print(
            f"[bold red]Could not connect to the Doing API at {api.BASE_URL}[/bold red]\n"
            "Make sure the backend is running."
        )
    else:
        console.print(f"[bold red]Unexpected error:[/bold red] {exc}")
    raise typer.Exit(code=1)


def _print_notes(task: dict) -> None:
    if task.get("notes"):
        console.print(f"       [dim]{task['notes']}[/dim]")


def _print_active_task(task: dict) -> None:
    ctx = f"  [dim][{task['context_name']}][/dim]" if task.get("context_name") else ""
    console.print(f"  [green bold]●[/green bold] [dim]#{task['id']}[/dim]  {task['title']}{ctx}")
    _print_notes(task)


def _print_paused_task(task: dict) -> None:
    ctx = f"  [dim][{task['context_name']}][/dim]" if task.get("context_name") else ""
    console.print(f"  [yellow]⏸[/yellow] [dim]#{task['id']}[/dim]  {task['title']}{ctx}")
    _print_notes(task)


def _print_done_task(task: dict) -> None:
    ctx = f"  [{task['context_name']}]" if task.get("context_name") else ""
    console.print(f"  [green]✓[/green] [dim]#{task['id']}  [strike]{task['title']}[/strike]{ctx}[/dim]")
    _print_notes(task)


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
def register():
    """Create a new Doing account."""
    email = typer.prompt("Email")
    password = typer.prompt("Password", hide_input=True)
    password_confirm = typer.prompt("Confirm password", hide_input=True)
    if password != password_confirm:
        if _json_mode:
            _output_json({"error": True, "detail": "Passwords do not match"})
        console.print("[bold red]Passwords do not match.[/bold red]")
        raise typer.Exit(code=1)
    try:
        data = api.register(email, password)
    except Exception as exc:
        _handle_api_error(exc)
    save_token(data["access_token"])
    if _json_mode:
        _output_json({"ok": True, "email": email})
    console.print(f"[bold green]Account created![/bold green] Logged in as [bold]{email}[/bold]")


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
    notes: str = typer.Option(None, "--notes", "-n", help="Optional notes"),
    context: int = typer.Option(None, "--context", "-c", help="Context ID"),
):
    """Add something to your plate."""
    try:
        task = api.create_task(title, notes, context)
    except Exception as exc:
        _handle_api_error(exc)
    if _json_mode:
        _output_json(task)
    console.print(f"[green bold]●[/green bold] Added: [bold]{task['title']}[/bold]  [dim](#{task['id']})[/dim]")


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
    console.print(f"  {icon} [dim]#{task['id']}[/dim]  {task['title']}{ctx}")
    if task.get("notes"):
        console.print(f"       [dim]{task['notes']}[/dim]")
    console.print(f"       [dim]Status: {task['status']}  Created: {task['created_at']}[/dim]")


@app.command()
def ls(
    context: int = typer.Option(None, "--context", "-c", help="Filter by context ID"),
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
    for t in tasks:
        _print_active_task(t)


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
    task_id: int = typer.Argument(..., help="ID of the task to mark done"),
):
    """Mark a task as done."""
    try:
        task = api.mark_done(task_id)
    except Exception as exc:
        _handle_api_error(exc)
    if _json_mode:
        _output_json(task)
    console.print(f"[green]✓[/green] Done: [bold]{task['title']}[/bold]")


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
    notes: str = typer.Option(None, "--notes", "-n", help="New notes"),
    context: int = typer.Option(None, "--context", "-c", help="Move to context ID"),
    no_context: bool = typer.Option(False, "--no-context", help="Remove context"),
):
    """Edit a task's title, notes, or context."""
    try:
        task = api.update_task(task_id, title=title, notes=notes,
                               context_id=context, clear_context=no_context)
    except Exception as exc:
        _handle_api_error(exc)
    if _json_mode:
        _output_json(task)
    console.print(f"[green bold]Updated:[/green bold] {task['title']}  [dim](#{task['id']})[/dim]")


@app.command()
def today(
    context: int = typer.Option(None, "--context", "-c", help="Filter by context ID"),
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
        console.print("\n[bold]Active[/bold]")
        for t in active:
            _print_active_task(t)

    if paused:
        console.print("\n[bold yellow]Paused[/bold yellow]")
        for t in paused:
            _print_paused_task(t)

    if done_tasks:
        console.print("\n[bold]Done[/bold]")
        for t in done_tasks:
            _print_done_task(t)

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
    _require_auth()
    try:
        ctx = api.create_context(name)
    except Exception as exc:
        _handle_api_error(exc)
    if _json_mode:
        _output_json(ctx)
    console.print(f"[green bold]Created context:[/green bold] {ctx['name']}  [dim](#{ctx['id']})[/dim]")


@context_app.command("rm")
def context_rm(
    context_id: int = typer.Argument(..., help="Context ID to delete"),
):
    """Delete a context (tasks keep their data, just lose the context)."""
    _require_auth()
    try:
        api.delete_context(context_id)
    except Exception as exc:
        _handle_api_error(exc)
    if _json_mode:
        _output_json({"deleted": True, "id": context_id})
    console.print(f"[dim]Deleted context #{context_id}.[/dim]")


if __name__ == "__main__":
    app()
