import json

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


def _require_auth():
    """Exit with a message if the user is not logged in."""
    if load_token() is None:
        console.print("[bold red]Not logged in.[/bold red] Run: [bold]doing login[/bold]")
        raise typer.Exit(code=1)


def _handle_api_error(exc: Exception):
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
def main(ctx: typer.Context):
    """Doing - track what you're working on."""
    if ctx.invoked_subcommand is None:
        _require_auth()
        ls(json_output=False)
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
    console.print(f"[bold green]Logged in[/bold green] as [bold]{email}[/bold]")


@app.command()
def register():
    """Create a new Doing account."""
    email = typer.prompt("Email")
    password = typer.prompt("Password", hide_input=True)
    password_confirm = typer.prompt("Confirm password", hide_input=True)
    if password != password_confirm:
        console.print("[bold red]Passwords do not match.[/bold red]")
        raise typer.Exit(code=1)
    try:
        data = api.register(email, password)
    except Exception as exc:
        _handle_api_error(exc)
    save_token(data["access_token"])
    console.print(f"[bold green]Account created![/bold green] Logged in as [bold]{email}[/bold]")


@app.command()
def logout():
    """Log out and clear stored credentials."""
    clear_token()
    console.print("[dim]Logged out.[/dim]")


@app.command()
def apikey(
    key: str = typer.Option(None, "--key", "-k", help="API key (starts with doing_)"),
):
    """Save an API key for authentication (get one from the web UI)."""
    if key is None:
        key = typer.prompt("API key", hide_input=True)
    if not key.startswith("doing_"):
        console.print("[bold red]Invalid API key.[/bold red] Keys start with [bold]doing_[/bold]")
        raise typer.Exit(code=1)
    save_token(key)
    console.print("[bold green]API key saved.[/bold green] You're all set.")


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
    console.print(f"[green bold]●[/green bold] Added: [bold]{task['title']}[/bold]  [dim](#{task['id']})[/dim]")


@app.command()
def ls(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """Show what's on your plate right now."""
    try:
        tasks = api.list_tasks(status="active")
    except Exception as exc:
        _handle_api_error(exc)
    if json_output:
        console.print_json(json.dumps(tasks))
        raise typer.Exit()
    if not tasks:
        console.print("Nothing on your plate. Add something: [bold]doing add 'task name'[/bold]")
        raise typer.Exit()
    for t in tasks:
        _print_active_task(t)


@app.command()
def log(
    date: str = typer.Option(None, "--date", "-d", help="Date (YYYY-MM-DD), defaults to today"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """List tasks marked done today (or on a given date)."""
    from datetime import date as date_cls
    query_date = date if date else date_cls.today().isoformat()
    try:
        tasks = api.list_tasks(status="done", date=query_date)
    except Exception as exc:
        _handle_api_error(exc)
    if json_output:
        console.print_json(json.dumps(tasks))
        raise typer.Exit()
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
    console.print(f"[green bold]Updated:[/green bold] {task['title']}  [dim](#{task['id']})[/dim]")


@app.command()
def today(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """Show everything from today, grouped by status."""
    try:
        data = api.get_today()
    except Exception as exc:
        _handle_api_error(exc)

    if json_output:
        console.print_json(json.dumps(data))
        raise typer.Exit()

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
    console.print(f"[dim]Deleted task #{task_id}.[/dim]")


@app.command()
def clear():
    """Mark ALL active tasks as done."""
    try:
        tasks = api.list_tasks(status="active")
    except Exception as exc:
        _handle_api_error(exc)

    if not tasks:
        console.print("Nothing to clear.")
        raise typer.Exit()

    for t in tasks:
        try:
            api.mark_done(t["id"])
        except Exception:
            console.print(f"[red]Failed to complete task #{t['id']}[/red]")
            continue
        console.print(f"[green]✓[/green] Done: [bold]{t['title']}[/bold]")

    console.print(f"\n[dim]Cleared {len(tasks)} task(s).[/dim]")


@app.command()
def contexts():
    """List all contexts."""
    try:
        ctx_list = api.list_contexts()
    except Exception as exc:
        _handle_api_error(exc)
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
    console.print(f"[dim]Deleted context #{context_id}.[/dim]")


if __name__ == "__main__":
    app()
