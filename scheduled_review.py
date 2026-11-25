"""Daily editorial review of the approved document library.

Each run (started by a systemd timer on workdays) picks the documents that are due,
oldest review first, runs the editorial review and publishes each result to the review
dashboard outbox, where it lands in the default manager's inbox.

* Library: the folder of final, approved DOCX files under their original names
  (the dashboard writes the clean approved version back here after final approval).
* Due: never reviewed, or last reviewed more than --interval-days ago (default 365).
* A document that fails (e.g. date fields not found) is recorded and skipped; it is
  retried after --retry-days or as soon as the file changes.
* If the LLM is unavailable the run stops without penalising any document.
* State lives in a small JSON ledger; runs are serialised with a lock file.

    python scheduled_review.py --check        # validate every library document, no LLM
    python scheduled_review.py --dry-run      # show what the next run would send
    python scheduled_review.py                # run (skips Thursday/Friday unless --force)
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import sys
import tempfile
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Tehran")
WORKDAYS = {5, 6, 0, 1, 2}  # Python weekday(): Sat=5, Sun=6, Mon=0, Tue=1, Wed=2 (Thu/Fri off)
DEFAULTS = {
    "library": "/opt/isms-review-center/agent/references",
    "outbox": "/opt/isms-review-center/agent/outbox",
    "state": "/opt/document-review/state/scheduled_review.json",
    "artifacts": "/opt/document-review/artifacts/scheduled",
    "rules": "/opt/document-review/config/scheduled_review_rules.txt",
    "requirements": "/opt/isms-review-center/agent/requirements",
}
RULE_KINDS = ("exclude", "editorial-only")



def document_title(key: str) -> str:
    """The document's real name: its library folder (docs/<name>/<code>.docx), else the file name."""
    path = PurePosixPath(key)
    parent = path.parent.name
    return parent if parent and parent != "docs" and path.parent != PurePosixPath(".") else path.stem

def log(message: str) -> None:
    print(f"{datetime.now(TZ):%Y-%m-%d %H:%M:%S} {message}", flush=True)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _skipped_name(path: Path, library: Path) -> bool:
    rel = path.relative_to(library)
    return any(part.startswith(".") for part in rel.parts) or path.name.startswith("~$")


def library_files(library: Path) -> list[Path]:
    """Every DOCX in the library, including subfolders (one folder per document is fine).

    Word lock files (~$...), hidden files/folders and non-DOCX files are ignored.
    Sorted by filename (the document code), then path.
    """
    files = [p for p in library.rglob("*")
             if p.is_file() and p.suffix.lower() == ".docx" and not _skipped_name(p, library)]
    return sorted(files, key=lambda p: (p.name, str(p)))


def ignored_files(library: Path) -> dict[str, list[Path]]:
    """Files in the library that the review never touches, grouped by extension (for --check)."""
    groups: dict[str, list[Path]] = {}
    for p in library.rglob("*"):
        if not p.is_file() or (p.suffix.lower() == ".docx" and not _skipped_name(p, library)):
            continue
        key = "lock/temp" if p.name.startswith("~$") or p.suffix.lower() == ".tmp" else (p.suffix.lower() or "(none)")
        groups.setdefault(key, []).append(p)
    return groups


def key_of(path: Path, library: Path) -> str:
    return path.relative_to(library).as_posix()


def load_rules(path: Path) -> list[tuple[str, str]]:
    """Read '<kind> <relative path or glob>' lines; kinds: exclude, editorial-only. '#' starts a comment.

        exclude         docs/نکات.docx
        editorial-only  docs/NDA-همکاران/*.docx
    """
    if not path.exists():
        return []
    rules = []
    for number, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        kind, _, pattern = line.partition(" ")
        pattern = pattern.strip()
        if kind not in RULE_KINDS or not pattern:
            raise ValueError(f"{path}:{number}: expected '<exclude|editorial-only> <path>', got {raw!r}")
        rules.append((kind, pattern))
    return rules


def rule_for(key: str, rules: list[tuple[str, str]]) -> str | None:
    """First rule whose pattern matches the document's library path (glob, case-sensitive)."""
    from fnmatch import fnmatchcase
    return next((kind for kind, pattern in rules if fnmatchcase(key, pattern)), None)


def load_state(path: Path) -> dict:
    if not path.exists():
        return {"documents": {}}
    data = json.loads(path.read_text(encoding="utf-8"))
    data.setdefault("documents", {})
    return data


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".state-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(state, handle, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _when(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def due_documents(files: list[Path], state: dict, now: datetime, interval_days: int, retry_days: int,
                  library: Path, panel_reviews: dict | None = None):
    """Return (due, waiting) where due is ordered: never reviewed first, then oldest review; ties by name."""
    due, waiting = [], []
    for path in files:
        entry = state["documents"].get(key_of(path, library), {})
        reviewed = [v for v in (entry.get("last_published"), (panel_reviews or {}).get(key_of(path, library))) if v]
        last_review = max(_when(v) for v in reviewed) if reviewed else None
        last_failure = _when(entry.get("last_failed"))
        if last_review and now - last_review < timedelta(days=interval_days):
            waiting.append((path, f"بازنگری بعدی پس از {(last_review + timedelta(days=interval_days)).date()}"))
            continue
        changed = entry.get("failed_sha256") and entry["failed_sha256"] != sha256(path)
        if last_failure and not changed and now - last_failure < timedelta(days=retry_days) \
                and (not last_review or last_failure > last_review):
            waiting.append((path, f"خطای قبلی؛ تلاش دوباره پس از {(last_failure + timedelta(days=retry_days)).date()}"))
            continue
        due.append(path)
    due.sort(key=lambda p: (max(state["documents"].get(key_of(p, library), {}).get("last_published") or "",
                                (panel_reviews or {}).get(key_of(p, library)) or ""), p.name, str(p)))
    return due, waiting


def run(args, client=None, now: datetime | None = None) -> int:
    from editorial_review import LLMUnavailable, preflight, publish, review

    now = now or datetime.now(TZ)
    library, outbox, state_path = Path(args.library), Path(args.outbox), Path(args.state)
    if not library.is_dir():
        log(f"ERROR library folder not found: {library}")
        return 2

    try:
        rules = load_rules(Path(args.rules))
    except ValueError as exc:
        log(f"ERROR {exc}")
        return 2
    all_files = library_files(library)
    kinds = {p: rule_for(key_of(p, library), rules) for p in all_files}
    excluded = [p for p in all_files if kinds[p] == "exclude"]
    files = [p for p in all_files if kinds[p] != "exclude"]
    editorial_only = {p for p in files if kinds[p] == "editorial-only"}
    if args.check:
        bad = 0
        for path in files:
            result = preflight(path, now, update_dates=path not in editorial_only)
            mark = "OK " if result["ok"] else "FIX"
            bad += not result["ok"]
            note = " (editorial only, dates unchanged)" if path in editorial_only else ""
            log(f"{mark} {key_of(path, library)} — {result['paragraphs']} paragraph(s){note}" +
                ("" if result["ok"] else " — " + " | ".join(result["problems"])))
        for path in excluded:
            log(f"EXCLUDED {key_of(path, library)}")
        from fnmatch import fnmatchcase
        for kind, pattern in rules:
            if not any(fnmatchcase(key_of(p, library), pattern) for p in all_files):
                log(f"WARNING rule matches no document: {kind} {pattern}")
        names = {}
        for path in files:
            names.setdefault(path.name, []).append(key_of(path, library))
        for name, paths in names.items():
            if len(paths) > 1:
                log(f"NOTE same filename in {len(paths)} places (each is reviewed separately): " + " ; ".join(paths))
        for kind, paths in sorted(ignored_files(library).items()):
            log(f"SKIP {len(paths)} {kind} file(s) — not reviewed" +
                (": " + " ; ".join(key_of(p, library) for p in paths) if kind == ".doc" else ""))
        log(f"{len(files)} document(s), {len(files) - bad} ready, {bad} need fixing, {len(excluded)} excluded")
        return 1 if bad else 0

    if not args.force and not args.dry_run and now.weekday() not in WORKDAYS:
        log("Not a workday (Thursday/Friday); nothing sent. Use --force to run anyway.")
        return 0
    if not outbox.is_dir():
        log(f"ERROR outbox folder not found: {outbox}")
        return 2

    state = load_state(state_path)
    panel_path = Path(args.state).with_name("request_reviews.json")  # written by request_review.py
    panel_reviews = json.loads(panel_path.read_text(encoding="utf-8")) if panel_path.exists() else {}
    due, waiting = due_documents(files, state, now, args.interval_days, args.retry_days, library, panel_reviews)
    log(f"Library: {len(files)} document(s); due: {len(due)}; waiting: {len(waiting)}; sending up to {args.per_run}")
    if args.dry_run:
        for path in due[:args.per_run]:
            log(f"WOULD SEND {key_of(path, library)}")
        for path, why in waiting[:20]:
            log(f"WAIT {key_of(path, library)} — {why}")
        return 0

    sent = 0
    skipped = 0
    from requirements_corpus import load as load_requirements
    clauses, req_warnings = load_requirements(getattr(args, "requirements", None))
    if clauses:
        log(f"Requirements: {len(clauses)} clause(s) from {len({c.source for c in clauses})} document(s)")
    for warning in req_warnings:
        log(f"WARNING {warning}")
    attempts = 0
    for path in due:
        if sent >= args.per_run or attempts >= args.per_run + args.max_extra_attempts:
            break
        key = key_of(path, library)
        entry = state["documents"].setdefault(key, {})
        digest = sha256(path)
        run_dir = Path(args.artifacts) / f"{now:%Y%m%d-%H%M%S}-{path.stem}"
        check = preflight(path, now, update_dates=path not in editorial_only)
        if not check["ok"]:
            # Cheap (no LLM) and expected for documents that need fixing: does not use up the run's attempts.
            entry.update({"last_failed": now.isoformat(), "failed_sha256": digest,
                          "last_error": " | ".join(check["problems"])[:500]})
            entry["failures"] = entry.get("failures", 0) + 1
            skipped += 1
            log(f"SKIP {key}: {' | '.join(check['problems'])[:300]}")
            save_state(state_path, state)
            continue
        attempts += 1
        try:
            log(f"REVIEW {key}")
            report = review(path, run_dir, client=client, now=now, update_dates=path not in editorial_only,
                            requirements=clauses, requirement_warnings=req_warnings, title=document_title(key))
            destination = publish(run_dir, outbox, library_path=key)
        except LLMUnavailable as exc:
            log(f"STOP LLM unavailable while reviewing {key}: {exc}")
            save_state(state_path, state)
            return 3
        except Exception as exc:  # one bad document must not block the rest of the library
            entry.update({"last_failed": now.isoformat(), "failed_sha256": digest,
                          "last_error": str(exc)[:500]})
            entry["failures"] = entry.get("failures", 0) + 1
            log(f"FAIL {key}: {str(exc)[:300]}")
            save_state(state_path, state)
            continue
        entry.update({"last_published": now.isoformat(), "published_sha256": digest,
                      "run_id": destination.name, "output_dir": str(run_dir),
                      "changes": report["summary"]["findings_total"], "last_error": None})
        sent += 1
        log(f"SENT {key} -> {destination.name} ({report['summary']['findings_total']} change(s))")
        save_state(state_path, state)
    log(f"Done: {sent} sent, {attempts - sent} failed, {skipped} skipped (need fixing)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--library", default=os.getenv("SCHEDULED_REVIEW_LIBRARY", DEFAULTS["library"]))
    ap.add_argument("--outbox", default=os.getenv("SCHEDULED_REVIEW_OUTBOX", DEFAULTS["outbox"]))
    ap.add_argument("--state", default=os.getenv("SCHEDULED_REVIEW_STATE", DEFAULTS["state"]))
    ap.add_argument("--artifacts", default=os.getenv("SCHEDULED_REVIEW_ARTIFACTS", DEFAULTS["artifacts"]))
    ap.add_argument("--requirements", default=os.getenv("SCHEDULED_REVIEW_REQUIREMENTS", DEFAULTS["requirements"]),
                    help="Folder of requirements documents taken into account by every review")
    ap.add_argument("--rules", default=os.getenv("SCHEDULED_REVIEW_RULES", DEFAULTS["rules"]),
                    help="Rules file: 'exclude <path>' / 'editorial-only <path>' lines (globs allowed)")
    ap.add_argument("--per-run", type=int, default=int(os.getenv("SCHEDULED_REVIEW_PER_RUN", "2")))
    ap.add_argument("--interval-days", type=int, default=int(os.getenv("SCHEDULED_REVIEW_INTERVAL_DAYS", "365")))
    ap.add_argument("--retry-days", type=int, default=int(os.getenv("SCHEDULED_REVIEW_RETRY_DAYS", "7")))
    ap.add_argument("--max-extra-attempts", type=int, default=5,
                    help="Extra documents to try in one run when some fail")
    ap.add_argument("--check", action="store_true", help="Validate every library document without the LLM")
    ap.add_argument("--dry-run", action="store_true", help="Show what would be sent; change nothing")
    ap.add_argument("--force", action="store_true", help="Run even on Thursday/Friday")
    args = ap.parse_args()

    lock_path = Path(args.state).with_suffix(".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            log("Another scheduled review is running; exiting.")
            return 0
        return run(args)


if __name__ == "__main__":
    sys.exit(main())
