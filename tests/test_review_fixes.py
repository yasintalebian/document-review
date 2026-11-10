import json
import zipfile
from pathlib import Path
from unittest import mock

from docx import Document

import corpus_review
from corpus_review import ReferenceParagraph, read_paragraphs, relevant_references, review_document
from docx_tracked_changes import create_tracked_docx


def document_xml(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        return archive.read("word/document.xml").decode("utf-8")


def test_table_paragraphs_are_read_once_in_order(tmp_path: Path) -> None:
    path = tmp_path / "table.docx"
    document = Document()
    document.add_paragraph("before")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).merge(table.cell(0, 1)).text = "merged"
    table.cell(1, 0).text = "left"
    table.cell(1, 1).text = "right"
    document.add_paragraph("after")
    document.save(path)

    assert read_paragraphs(path) == ["before", "merged", "left", "right", "after"]


def test_tracked_change_lands_inside_table(tmp_path: Path) -> None:
    source = tmp_path / "source.docx"
    output = tmp_path / "output.docx"
    document = Document()
    document.add_paragraph("intro")
    document.add_table(rows=1, cols=1).cell(0, 0).text = "old cell"
    document.save(source)

    create_tracked_docx(source, output, {1: ("old cell", "new cell")})

    xml = document_xml(output)
    table_xml = xml[xml.index("<w:tbl>"):xml.index("</w:tbl>")]
    assert "<w:delText>old cell</w:delText>" in table_xml
    assert "new cell" in table_xml


def test_lookup_matches_arabic_and_persian_letter_variants() -> None:
    references = [ReferenceParagraph("policy.docx", 0, "سیاست کنترل دسترسی می‌شود")]

    assert relevant_references("سياست", references)
    assert relevant_references("میشود", references)


class FakeClient:
    def complete(self, messages, temperature=0.0):
        if "ISO/IEC 27001" in messages[0]["content"]:
            return json.dumps({"findings": [{
                "reference_id": "A.8",
                "status": "gap",
                "rationale": "missing",
                "suggested_text": "ISO proposal",
                "target_paragraph": 0,
            }]})
        return json.dumps({
            "decision": "conflict",
            "category": "rule",
            "rationale": "contradicts reference",
            "suggested_text": "corpus proposal",
        })


def test_iso_proposal_does_not_overwrite_corpus_proposal(tmp_path: Path) -> None:
    corpus = tmp_path / "references"
    corpus.mkdir()
    reference = Document()
    reference.add_paragraph("password length is 13 characters")
    reference.save(corpus / "approved.docx")

    candidate = tmp_path / "candidate.docx"
    document = Document()
    document.add_paragraph("password length is 8 characters")
    document.save(candidate)

    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"requirements": [
        {"reference_id": "A.8", "title": "Tech", "summary": "access", "keywords": ["password"]},
    ]}), encoding="utf-8")

    output = tmp_path / "review.docx"
    with mock.patch.object(corpus_review.LLMClient, "from_environment", return_value=FakeClient()):
        review_document(candidate, corpus, output, tmp_path / "report.json", baseline)

    xml = document_xml(output)
    assert "corpus proposal" in xml
    assert "[A.8 - Tech] ISO proposal" in xml
