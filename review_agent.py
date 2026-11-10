"""Review two DOCX versions and produce a human-reviewable tracked-changes file."""

from __future__ import annotations

import argparse
import difflib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from docx import Document

from docx_tracked_changes import create_tracked_docx, iter_paragraphs
from llm_client import LLMClient, LLMConfigurationError, LLMRequestError


@dataclass
class Change:
    kind: str
    old_paragraph: int | None
    new_paragraph: int | None
    old_text: str
    new_text: str
    decision: str = "needs_review"
    category: str = "content_change"
    rationale: str = ""
    suggested_text: str = ""


def read_paragraphs(path: str | Path) -> list[str]:
    return [paragraph.text for paragraph in iter_paragraphs(Document(str(path)))]


def compare_documents(old: list[str], new: list[str]) -> list[Change]:
    matcher = difflib.SequenceMatcher(a=old, b=new, autojunk=False)
    changes: list[Change] = []
    for tag, old_start, old_end, new_start, new_end in matcher.get_opcodes():
        if tag == "equal":
            continue
        old_slice = old[old_start:old_end]
        new_slice = new[new_start:new_end]
        for offset in range(max(len(old_slice), len(new_slice))):
            old_text = old_slice[offset] if offset < len(old_slice) else ""
            new_text = new_slice[offset] if offset < len(new_slice) else ""
            kind = "replace" if old_text and new_text else "delete" if old_text else "insert"
            changes.append(Change(
                kind=kind,
                old_paragraph=old_start + offset if old_text else None,
                new_paragraph=new_start + offset if new_text else None,
                old_text=old_text,
                new_text=new_text,
            ))
    return changes


def _parse_model_json(text: str) -> dict[str, str]:
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        return {"rationale": text}
    try:
        value = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {"rationale": text}
    return {key: str(value.get(key, "")) for key in ("decision", "category", "rationale", "suggested_text")}


def classify_change(client: LLMClient, change: Change) -> None:
    messages = [
        {
            "role": "system",
            "content": (
                "You review controlled ISMS documents. Return only JSON with keys "
                "decision, category, rationale, suggested_text. decision must be "
                "approve, reject, or needs_review. Never invent policy requirements."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {"change_type": change.kind, "old_text": change.old_text, "new_text": change.new_text},
                ensure_ascii=False,
            ),
        },
    ]
    result = _parse_model_json(client.complete(messages))
    change.decision = result.get("decision") or "needs_review"
    change.category = result.get("category") or "content_change"
    change.rationale = result.get("rationale", "")
    change.suggested_text = result.get("suggested_text", "")


def review(old_path: str | Path, new_path: str | Path, output_path: str | Path, report_path: str | Path) -> dict:
    changes = compare_documents(read_paragraphs(old_path), read_paragraphs(new_path))
    try:
        client = LLMClient.from_environment()
    except LLMConfigurationError as exc:
        client = None
        configuration_note = str(exc)
    else:
        configuration_note = "Internal LLM classification enabled."

    for change in changes:
        if client is None:
            change.rationale = "LLM classification was not run. Configure the internal endpoint."
        else:
            try:
                classify_change(client, change)
            except LLMRequestError as exc:
                change.rationale = f"LLM classification failed: {exc}"

    replacements = {
        change.new_paragraph: (change.old_text, change.new_text)
        for change in changes
        if change.kind == "replace" and change.new_paragraph is not None
    }
    insertions = {
        change.new_paragraph: change.new_text
        for change in changes
        if change.kind == "insert" and change.new_paragraph is not None
    }
    deletions = [change.old_text for change in changes if change.kind == "delete"]
    create_tracked_docx(new_path, output_path, replacements, insertions, deletions)
    report = {
        "old_document": str(old_path),
        "new_document": str(new_path),
        "tracked_output": str(output_path),
        "configuration": configuration_note,
        "change_count": len(changes),
        "changes": [asdict(change) for change in changes],
    }
    Path(report_path).parent.mkdir(parents=True, exist_ok=True)
    Path(report_path).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old", required=True, help="previous approved DOCX")
    parser.add_argument("--new", required=True, help="new DOCX to review")
    parser.add_argument("--output", default="artifacts/reviewed_with_track_changes.docx")
    parser.add_argument("--report", default="artifacts/review_report.json")
    args = parser.parse_args()
    report = review(args.old, args.new, args.output, args.report)
    print(f"Detected {report['change_count']} change(s).")
    print(f"Tracked document: {args.output}")
    print(f"Review report: {args.report}")


if __name__ == "__main__":
    main()
