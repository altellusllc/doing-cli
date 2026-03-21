import os
import time as _time

import httpx

from doing_cli.auth import load_token

BASE_URL = os.environ.get("DOING_API_URL", "https://doingapp.co")


def _local_tz() -> str:
    try:
        # Works on most Unix systems
        return os.path.realpath("/etc/localtime").split("zoneinfo/")[1]
    except (IndexError, OSError):
        pass
    tz = os.environ.get("TZ")
    if tz:
        return tz
    return _time.tzname[0]


def _client() -> httpx.Client:
    headers = {}
    token = load_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return httpx.Client(base_url=BASE_URL, timeout=10.0, headers=headers)


def register(email: str, password: str) -> dict:
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        r = c.post("/auth/register", json={"email": email, "password": password})
        r.raise_for_status()
        return r.json()


def login(email: str, password: str) -> dict:
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        r = c.post("/auth/login", json={"email": email, "password": password})
        r.raise_for_status()
        return r.json()


def get_me() -> dict:
    with _client() as c:
        r = c.get("/auth/me")
        r.raise_for_status()
        return r.json()


def create_task(title: str, notes: str | None = None, context_id: int | None = None) -> dict:
    payload: dict = {"title": title}
    if notes is not None:
        payload["notes"] = notes
    if context_id is not None:
        payload["context_id"] = context_id
    with _client() as c:
        r = c.post("/tasks", json=payload)
        r.raise_for_status()
        return r.json()


def get_task(task_id: int) -> dict:
    with _client() as c:
        r = c.get(f"/tasks/{task_id}")
        r.raise_for_status()
        return r.json()


def list_tasks(status: str | None = None, date: str | None = None,
               context_id: int | None = None) -> list[dict]:
    params: dict = {"tz": _local_tz()}
    if status is not None:
        params["status"] = status
    if date is not None:
        params["date"] = date
    if context_id is not None:
        params["context_id"] = context_id
    with _client() as c:
        r = c.get("/tasks", params=params)
        r.raise_for_status()
        return r.json()


def mark_done(task_id: int) -> dict:
    with _client() as c:
        r = c.post(f"/tasks/{task_id}/done")
        r.raise_for_status()
        return r.json()


def reopen_task(task_id: int) -> dict:
    with _client() as c:
        r = c.post(f"/tasks/{task_id}/reopen")
        r.raise_for_status()
        return r.json()


def pause_task(task_id: int) -> dict:
    with _client() as c:
        r = c.post(f"/tasks/{task_id}/pause")
        r.raise_for_status()
        return r.json()


def resume_task(task_id: int) -> dict:
    with _client() as c:
        r = c.post(f"/tasks/{task_id}/resume")
        r.raise_for_status()
        return r.json()


def update_task(task_id: int, title: str | None = None, notes: str | None = None,
                context_id: int | None = None, clear_context: bool = False) -> dict:
    payload: dict = {}
    if title is not None:
        payload["title"] = title
    if notes is not None:
        payload["notes"] = notes
    if clear_context:
        payload["clear_context"] = True
    elif context_id is not None:
        payload["context_id"] = context_id
    with _client() as c:
        r = c.patch(f"/tasks/{task_id}", json=payload)
        r.raise_for_status()
        return r.json()


def delete_task(task_id: int) -> None:
    with _client() as c:
        r = c.delete(f"/tasks/{task_id}")
        r.raise_for_status()


def get_today(context_id: int | None = None) -> dict:
    params: dict = {"tz": _local_tz()}
    if context_id is not None:
        params["context_id"] = context_id
    with _client() as c:
        r = c.get("/today", params=params)
        r.raise_for_status()
        return r.json()


# --- Contexts ---


def list_contexts() -> list[dict]:
    with _client() as c:
        r = c.get("/contexts")
        r.raise_for_status()
        return r.json()


def create_context(name: str) -> dict:
    with _client() as c:
        r = c.post("/contexts", json={"name": name})
        r.raise_for_status()
        return r.json()


def delete_context(context_id: int) -> None:
    with _client() as c:
        r = c.delete(f"/contexts/{context_id}")
        r.raise_for_status()
