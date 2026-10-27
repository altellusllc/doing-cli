import os
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

from doing_cli.auth import load_token

BASE_URL = os.environ.get("DOING_API_URL", "https://doingapp.co")


def _is_iana_tz(name: str) -> bool:
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return False
    return True


def _local_tz() -> str | None:
    """IANA name of the local timezone, or None if it can't be determined.

    TZ wins over /etc/localtime, as it does for the OS itself; containers
    commonly set TZ while /etc/localtime still points at UTC. Abbreviations
    like "MST" are never sent: the server would treat them as fixed offsets
    with no DST. When this returns None the server uses the account timezone.
    """
    candidates = []
    if tz := os.environ.get("TZ", "").lstrip(":"):
        candidates.append(tz)
    try:
        candidates.append(os.path.realpath("/etc/localtime").split("zoneinfo/")[1])
    except (IndexError, OSError):
        pass
    return next((name for name in candidates if _is_iana_tz(name)), None)


def _tz_params() -> dict:
    tz = _local_tz()
    return {"tz": tz} if tz else {}


def _client() -> httpx.Client:
    headers = {}
    token = load_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return httpx.Client(base_url=BASE_URL, timeout=10.0, headers=headers)


def register(token: str, password: str) -> dict:
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        r = c.post("/auth/register", json={"token": token, "password": password})
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


def create_task(title: str, notes: str | None = None, context_id: int | None = None,
                due: str | None = None, recurrence: str | None = None) -> dict:
    payload: dict = {"title": title}
    if notes is not None:
        payload["notes"] = notes
    if context_id is not None:
        payload["context_id"] = context_id
    if due is not None:
        payload["due"] = due
    if recurrence is not None:
        payload["recurrence"] = recurrence
    with _client() as c:
        r = c.post("/tasks", json=payload, params=_tz_params())
        r.raise_for_status()
        return r.json()


def get_task(task_id: int) -> dict:
    with _client() as c:
        r = c.get(f"/tasks/{task_id}")
        r.raise_for_status()
        return r.json()


def list_tasks(status: str | None = None, date: str | None = None,
               context_id: int | None = None) -> list[dict]:
    params: dict = _tz_params()
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
        r = c.post(f"/tasks/{task_id}/done", params=_tz_params())
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


def touch_task(task_id: int) -> dict:
    with _client() as c:
        r = c.post(f"/tasks/{task_id}/touch")
        r.raise_for_status()
        return r.json()


def resume_task(task_id: int) -> dict:
    with _client() as c:
        r = c.post(f"/tasks/{task_id}/resume")
        r.raise_for_status()
        return r.json()


def update_task(task_id: int, title: str | None = None, notes: str | None = None,
                context_id: int | None = None, clear_context: bool = False,
                due: str | None = None, recurrence: str | None = None,
                clear_due: bool = False, clear_recurrence: bool = False) -> dict:
    payload: dict = {}
    if title is not None:
        payload["title"] = title
    if notes is not None:
        payload["notes"] = notes
    if clear_context:
        payload["clear_context"] = True
    elif context_id is not None:
        payload["context_id"] = context_id
    if clear_due:
        payload["clear_due"] = True
    elif due is not None:
        payload["due"] = due
    if clear_recurrence:
        payload["clear_recurrence"] = True
    elif recurrence is not None:
        payload["recurrence"] = recurrence
    with _client() as c:
        r = c.patch(f"/tasks/{task_id}", json=payload, params=_tz_params())
        r.raise_for_status()
        return r.json()


def snooze_task(task_id: int, minutes: int | None = None, preset: str | None = None) -> dict:
    payload: dict = {"minutes": minutes} if minutes is not None else {"preset": preset}
    with _client() as c:
        r = c.post(f"/tasks/{task_id}/snooze", json=payload, params=_tz_params())
        r.raise_for_status()
        return r.json()


def delete_task(task_id: int) -> None:
    with _client() as c:
        r = c.delete(f"/tasks/{task_id}")
        r.raise_for_status()


def get_stats(context_id: int | None = None) -> dict:
    params: dict = _tz_params()
    if context_id is not None:
        params["context_id"] = context_id
    with _client() as c:
        r = c.get("/stats", params=params)
        r.raise_for_status()
        return r.json()


def get_done_history(limit: int = 7, before: str | None = None,
                     context_id: int | None = None) -> dict:
    params: dict = {**_tz_params(), "limit": limit}
    if before is not None:
        params["before"] = before
    if context_id is not None:
        params["context_id"] = context_id
    with _client() as c:
        r = c.get("/done", params=params)
        r.raise_for_status()
        return r.json()


def get_today(context_id: int | None = None) -> dict:
    params: dict = _tz_params()
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


def get_context(context_id: int) -> dict:
    with _client() as c:
        r = c.get(f"/contexts/{context_id}")
        r.raise_for_status()
        return r.json()


def update_context(context_id: int, name: str, icon: str | None = None) -> dict:
    payload: dict = {"name": name}
    if icon is not None:
        payload["icon"] = icon
    with _client() as c:
        r = c.put(f"/contexts/{context_id}", json=payload)
        r.raise_for_status()
        return r.json()


def snooze_context(context_id: int) -> dict:
    params: dict = _tz_params()
    with _client() as c:
        r = c.post(f"/contexts/{context_id}/snooze", params=params)
        r.raise_for_status()
        return r.json()


def unsnooze_context(context_id: int) -> dict:
    with _client() as c:
        r = c.post(f"/contexts/{context_id}/unsnooze")
        r.raise_for_status()
        return r.json()


def delete_context(context_id: int) -> None:
    with _client() as c:
        r = c.delete(f"/contexts/{context_id}")
        r.raise_for_status()
