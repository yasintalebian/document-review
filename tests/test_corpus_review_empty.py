from pathlib import Path

from docx import Document

from corpus_review import load_reference_corpus


def test_reference_paragraph_indices_skip_empty_paragraphs(tmp_path: Path) -> None:
    path = tmp_path / "reference.docx"
    document = Document()
    document.add_paragraph("")
    document.add_paragraph("approved clause")
    document.save(path)

    references = load_reference_corpus(tmp_path)

    assert references[0].paragraph == 1
