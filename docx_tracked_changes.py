"""OOXML helpers for creating reviewable Word tracked changes."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn


def _run_text(parent: object, text: str, deleted: bool = False) -> None:
    run = OxmlElement("w:r")
    text_element = OxmlElement("w:delText" if deleted else "w:t")
    if text.startswith(" ") or text.endswith(" ") or "  " in text:
        text_element.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    text_element.text = text
    run.append(text_element)
    parent.append(run)


def _revision(parent: object, tag: str, text: str, revision_id: int, author: str) -> None:
    revision = OxmlElement(f"w:{tag}")
    revision.set(qn("w:id"), str(revision_id))
    revision.set(qn("w:author"), author)
    revision.set(qn("w:date"), datetime.now(timezone.utc).isoformat())
    _run_text(revision, text, deleted=tag == "del")
    parent.append(revision)


def replace_paragraph_with_revision(
    paragraph: object,
    old_text: str,
    new_text: str,
    revision_id: int,
    author: str = "ISMS Review Agent",
) -> None:
    """Show the old paragraph as deleted and the new paragraph as inserted.

    Paragraph properties are retained.  Formatting inside changed runs is
    intentionally simplified because the source and target text are supplied
    by the document comparison layer and must remain auditable.
    """

    p = paragraph._p
    for child in list(p):
        if child.tag != qn("w:pPr"):
            p.remove(child)
    if old_text:
        _revision(p, "del", old_text, revision_id, author)
    if new_text:
        _revision(p, "ins", new_text, revision_id + 1, author)


def mark_inserted_paragraph(
    paragraph: object,
    text: str,
    revision_id: int,
    author: str = "ISMS Review Agent",
) -> None:
    p = paragraph._p
    for child in list(p):
        if child.tag != qn("w:pPr"):
            p.remove(child)
    _revision(p, "ins", text, revision_id, author)


def append_deleted_paragraph(
    document: object,
    text: str,
    revision_id: int,
    author: str = "ISMS Review Agent",
) -> None:
    """Append a deleted paragraph when its original position no longer exists."""
    paragraph = document.add_paragraph()
    _revision(paragraph._p, "del", text, revision_id, author)


def append_inserted_paragraph(
    document: object,
    text: str,
    revision_id: int,
    author: str = "ISMS Review Agent",
) -> None:
    paragraph = document.add_paragraph()
    _revision(paragraph._p, "ins", text, revision_id, author)


def create_tracked_docx(
    source_path: str | Path,
    output_path: str | Path,
    replacements: dict[int, tuple[str, str]],
    insertions: dict[int, str] | None = None,
    deletions: list[str] | None = None,
    appended_insertions: list[str] | None = None,
) -> None:
    """Create a DOCX with proposed changes visibly marked for human review."""

    document = Document(str(source_path))
    insertions = insertions or {}
    deletions = deletions or []
    appended_insertions = appended_insertions or []
    for index, (old_text, new_text) in replacements.items():
        if 0 <= index < len(document.paragraphs):
            replace_paragraph_with_revision(document.paragraphs[index], old_text, new_text, index * 2 + 1)
    for index, text in insertions.items():
        if 0 <= index < len(document.paragraphs):
            mark_inserted_paragraph(document.paragraphs[index], text, index * 2 + 1)
    for offset, text in enumerate(deletions):
        append_deleted_paragraph(document, text, 100000 + offset)
    for offset, text in enumerate(appended_insertions):
        append_inserted_paragraph(document, text, 200000 + offset)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    document.save(str(output_path))
