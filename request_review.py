"""Review documents uploaded in the review panel ("send for review" page).

The panel writes each upload to the requests folder as <REQ-…>/ (request.json + the DOCX). This
script (started by a systemd path unit the moment a request appears, plus a short fallback timer)
reviews every pending request and publishes the result to the outbox, where the panel registers it
in the manager's inbox. Progress is written to <REQ-…>/status.json, which the panel shows.

    mode library   new organisation document; the manifest carries its future library path
                   (docs/<title>/<file>), so the approved copy lands in the reference library
    mode one_time  reviewed once; marked review_mode=one_time and never written to the library

Dates are updated when the standard template fields are found; otherwise the review is editorial
only and the status says so. Requirements documents are taken into account. If the LLM is
unavailable the request stays queued and is retried on the next run.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
import tempfile
import time
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Tehran")
REQ_RE = re.compile(r"^REQ-\d{8}-\d{6}-[0-9a-f]{6}$")
DEFAULTS = {
    "requests": "/opt/isms-review-center/agent/requests",
    "outbox": "/opt/isms-review-center/agent/outbox",
    "requirements": "/opt/isms-review-center/agent/requirements",
    "artifacts": "/opt/document-review/artifacts/requests",
    "state": "/opt/document-review/state/request_reviews.json",
}


def log(message: str) -> None:
    print(f"{datetime.now(TZ):%Y-%m-%d %H:%M:%S} {message}", flush=True)


def read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def write_json(path: Path, data: dict, mode: int = 0o640) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".status-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
    os.chmod(tmp, mode)
    try:  # keep the folder's group (the panel's) so the panel can read the status
        os.chown(tmp, -1, path.parent.stat().st_gid)
    except OSError:
        pass
    os.replace(tmp, path)


def set_status(folder: Path, state: str, message: str = "", **extra) -> None:
    status = read_json(folder / "status.json")
    status.update({"state": state, "message": message, "updated_at": datetime.now(TZ).isoformat(), **extra})
    write_json(folder / "status.json", status)


def pending(requests: Path) -> list[Path]:
    """Request folders not yet published or failed, oldest first."""
    if not requests.is_dir():
        return []
    out = []
    for folder in sorted(p for p in requests.iterdir() if p.is_dir() and REQ_RE.fullmatch(p.name)):
        if read_json(folder / "status.json").get("state") not in ("published", "failed"):
            out.append(folder)
    return out


def _validate(folder: Path) -> dict:
    req = read_json(folder / "request.json")
    if req.get("request_id") != folder.name:
        raise ValueError("request.json نامعتبر است.")
    if req.get("mode") not in ("library", "one_time"):
        raise ValueError("نوع بازنگری نامعتبر است.")
    name = req.get("filename") or ""
    if not name.lower().endswith(".docx") or "/" in name or "\\" in name or name.startswith("."):
        raise ValueError("نام فایل نامعتبر است.")
    path = folder / name
    if not path.is_file():
        raise ValueError("فایل سند در درخواست یافت نشد.")
    if req.get("sha256") and hashlib.sha256(path.read_bytes()).hexdigest() != req["sha256"]:
        raise ValueError("فایل با چکیدهٔ ثبت‌شده مطابقت ندارد (انتقال ناقص؟).")
    library_path = req.get("library_path") or ""
    if req["mode"] == "library":
        lp = PurePosixPath(library_path)
        if (not library_path or lp.is_absolute() or lp.parts[0] != "docs" or lp.name != name
                or any(part in ("", ".", "..") or part.startswith(".") for part in lp.parts)):
            raise ValueError("مسیر کتابخانه نامعتبر است.")
    elif library_path:
        raise ValueError("بازنگری یک‌باره نباید مسیر کتابخانه داشته باشد.")
    req["path"] = path
    return req


def process(folder: Path, args, client=None, clauses=(), req_warnings=(), now=None) -> str:
    """Review one request. Returns 'published', 'failed' or 'retry' (LLM unavailable)."""
    from editorial_review import LLMUnavailable, preflight, publish, review

    now = now or datetime.now(TZ)
    try:
        req = _validate(folder)
    except ValueError as exc:
        set_status(folder, "failed", str(exc))
        log(f"FAIL {folder.name}: {exc}")
        return "failed"
    path = req["path"]
    basic = preflight(path, now, update_dates=False)
    if not basic["ok"]:
        message = " | ".join(basic["problems"])
        set_status(folder, "failed", message)
        log(f"FAIL {folder.name}: {message}")
        return "failed"
    full = preflight(path, now)
    update_dates = full["ok"]
    note = "" if update_dates else "فیلدهای تاریخ قالب استاندارد پیدا نشد؛ فقط بازنگری نگارشی انجام شد."
    status = read_json(folder / "status.json")
    attempt = int(status.get("attempts", 0)) + 1
    set_status(folder, "reviewing", "", attempts=attempt)
    run_dir = Path(args.artifacts) / f"{folder.name}-{attempt}"
    log(f"REVIEW {folder.name} ({req['mode']}) {req['filename']}")
    try:
        report = review(path, run_dir, client=client, now=now, update_dates=update_dates,
                        requirements=list(clauses), requirement_warnings=list(req_warnings))
        destination = publish(run_dir, args.outbox, library_path=req.get("library_path") or None,
                              extra={"review_mode": req["mode"], "request_id": folder.name, "title": req.get("title")})
    except LLMUnavailable as exc:
        set_status(folder, "queued", "مدل زبانی در دسترس نبود؛ به‌طور خودکار دوباره تلاش می‌شود.", attempts=attempt)
        log(f"RETRY {folder.name}: LLM unavailable: {exc}")
        return "retry"
    except Exception as exc:  # one bad upload must not block the others
        set_status(folder, "failed", f"خطا در بازنگری: {str(exc)[:300]}", attempts=attempt)
        log(f"FAIL {folder.name}: {exc}")
        return "failed"
    summary = report["summary"]
    message = f"{summary.get('applied_changes', summary['findings_total'])} اصلاح اعمال شد"
    if summary.get("requirement_gaps"):
        message += f"؛ {summary['requirement_gaps']} الزام پوشش‌داده‌نشده در گزارش"
    if note:
        message += "؛ " + note
    set_status(folder, "published", message, run_id=destination.name, attempts=attempt)
    if req["mode"] == "library":  # the yearly cycle starts from today for this new document
        state_path = Path(args.state)
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state = read_json(state_path)
        state[req["library_path"]] = now.isoformat()
        write_json(state_path, state, 0o600)
    log(f"SENT {folder.name} -> {destination.name}: {message}")
    return "published"


def run(args, client=None, now=None) -> int:
    from requirements_corpus import load
    requests = Path(args.requests)
    clauses, req_warnings = load(args.requirements)
    handled = set()
    while True:
        todo = [f for f in pending(requests) if f.name not in handled]
        if not todo:
            time.sleep(args.settle)
            todo = [f for f in pending(requests) if f.name not in handled]  # arrived while finishing
            if not todo:
                return 0
        for folder in todo:
            handled.add(folder.name)
            if process(folder, args, client, clauses, req_warnings, now) == "retry":
                return 3  # LLM down: stop; the fallback timer retries later


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--requests", default=os.getenv("REQUEST_REVIEW_REQUESTS", DEFAULTS["requests"]))
    ap.add_argument("--outbox", default=os.getenv("REQUEST_REVIEW_OUTBOX", DEFAULTS["outbox"]))
    ap.add_argument("--requirements", default=os.getenv("REQUEST_REVIEW_REQUIREMENTS", DEFAULTS["requirements"]))
    ap.add_argument("--artifacts", default=os.getenv("REQUEST_REVIEW_ARTIFACTS", DEFAULTS["artifacts"]))
    ap.add_argument("--state", default=os.getenv("REQUEST_REVIEW_STATE", DEFAULTS["state"]),
                    help="Library documents reviewed via the panel (read by the scheduled review)")
    ap.add_argument("--settle", type=float, default=2.0, help=argparse.SUPPRESS)
    args = ap.parse_args()
    lock_path = Path(args.state).with_suffix(".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0  # the running instance keeps scanning until nothing is pending
        return run(args)


if __name__ == "__main__":
    sys.exit(main())
