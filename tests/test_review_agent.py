from pathlib import Path

from docx import Document

from review_agent import compare_documents, review


def make_doc(path: Path, paragraphs: list[str]) -> None:
    document = Document()
    for text in paragraphs:
        document.add_paragraph(text)
    document.save(path)


def test_compare_documents_detects_replacement_and_insertion() -> None:
    changes = compare_documents(["one", "two"], ["one", "two changed", "three"])
    assert [change.kind for change in changes] == ["replace", "insert"]
    assert changes[0].old_text == "two"
    assert changes[0].new_text == "two changed"


def test_review_creates_report_and_tracked_docx(tmp_path: Path) -> None:
    old = tmp_path / "old.docx"
    new = tmp_path / "new.docx"
    output = tmp_path / "review.docx"
    report = tmp_path / "report.json"
    make_doc(old, ["approved text"])
    make_doc(new, ["updated text"])

    result = review(old, new, output, report)

    assert result["change_count"] == 1
    assert output.exists()
    assert report.exists()
    assert output.stat().st_size > 0
