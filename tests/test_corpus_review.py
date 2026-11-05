from pathlib import Path

from docx import Document

from corpus_review import load_reference_corpus, promote_document, relevant_references


def make_doc(path: Path, text: str) -> None:
    document = Document()
    document.add_paragraph(text)
    document.save(path)


def test_reference_lookup_and_promotion(tmp_path: Path) -> None:
    incoming = tmp_path / "policy.docx"
    corpus = tmp_path / "references"
    make_doc(incoming, "حداکثر دو روز دورکاری در هفته")
    promote_document(incoming, corpus)

    references = load_reference_corpus(corpus)
    matches = relevant_references("دورکاری چند روز در هفته است؟", references)

    assert len(references) == 1
    assert matches[0].source == "policy.docx"
