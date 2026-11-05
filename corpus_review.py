"""Review one DOCX against an approved document corpus.

The corpus contains the organization's accepted policy language. A candidate
document is checked against the most relevant corpus paragraphs for
contradictions. The result is saved as a tracked-changes DOCX and a JSON
report. A document is added to the corpus only through the explicit
``--promote`` command after human approval.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from docx import Document

from docx_tracked_changes import create_tracked_docx
from llm_client import LLMClient, LLMConfigurationError, LLMRequestError


@dataclass(frozen=True)
class ReferenceParagraph:
    source: str
    paragraph: int
    text: str


@dataclass
class Finding:
    paragraph: int
    text: str
    decision: str = "needs_review"
    category: str = "no_relevant_conflict"
    rationale: str = ""
    suggested_text: str = ""
    references: list[str] | None = None


def read_paragraphs(path: str | Path) -> list[str]:
    return [paragraph.text.strip() for paragraph in Document(str(path)).paragraphs]


def load_reference_corpus(directory: str | Path) -> list[ReferenceParagraph]:
    root = Path(directory)
    references: list[ReferenceParagraph] = []
    for path in sorted(root.glob("*.docx")):
        for index, text in enumerate(read_paragraphs(path)):
            if text:
                references.append(ReferenceParagraph(path.name, index, text))
    return references


def _tokens(text: str) -> set[str]:
    return {token for token in re.findall(r"[\wآ-ی]+", text.lower()) if len(token) > 1}


def relevant_references(text: str, references: list[ReferenceParagraph], limit: int = 5) -> list[ReferenceParagraph]:
    query = _tokens(text)
    scored = []
    for reference in references:
        overlap = len(query & _tokens(reference.text))
        if overlap:
            scored.append((overlap, reference))
    scored.sort(key=lambda item: (-item[0], item[1].source, item[1].paragraph))
    return [reference for _, reference in scored[:limit]]


def _parse_json(text: str) -> dict[str, str]:
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        return {"rationale": text}
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {"rationale": text}
    return {key: str(data.get(key, "")) for key in ("decision", "category", "rationale", "suggested_text")}


def classify_against_corpus(client: LLMClient, text: str, references: list[ReferenceParagraph]) -> dict[str, str]:
    context = "\n".join(f"[{item.source} p{item.paragraph + 1}] {item.text}" for item in references)
    messages = [
        {
            "role": "system",
            "content": (
                "You are an ISMS consistency reviewer. Compare the candidate paragraph "
                "with the approved reference paragraphs. Return only JSON with keys "
                "decision, category, rationale, suggested_text. decision must be "
                "consistent, conflict, or needs_review. Use conflict only when the "
                "candidate contradicts an approved requirement. Never invent a rule."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {"candidate": text, "approved_references": context},
                ensure_ascii=False,
            ),
        },
    ]
    return _parse_json(client.complete(messages))


def review_document(document_path: str | Path, corpus_dir: str | Path, output_path: str | Path, report_path: str | Path) -> dict:
    references = load_reference_corpus(corpus_dir)
    candidate_paragraphs = read_paragraphs(document_path)
    findings: list[Finding] = []
    try:
        client = LLMClient.from_environment()
        configuration = "Internal LLM consistency review enabled."
    except LLMConfigurationError as exc:
        client = None
        configuration = str(exc)

    replacements: dict[int, tuple[str, str]] = {}
    for index, text in enumerate(candidate_paragraphs):
        if not text:
            continue
        matched = relevant_references(text, references)
        finding = Finding(
            paragraph=index,
            text=text,
            references=[f"{item.source} (paragraph {item.paragraph + 1})" for item in matched],
        )
        if client is None:
            finding.rationale = "LLM classification was not run. Configure the internal endpoint."
        elif matched:
            try:
                result = classify_against_corpus(client, text, matched)
                finding.decision = result.get("decision") or "needs_review"
                finding.category = result.get("category") or "needs_review"
                finding.rationale = result.get("rationale", "")
                finding.suggested_text = result.get("suggested_text", "")
                if finding.suggested_text and finding.suggested_text != text and finding.decision in {"conflict", "needs_review"}:
                    replacements[index] = (text, finding.suggested_text)
            except LLMRequestError as exc:
                finding.rationale = f"LLM classification failed: {exc}"
        else:
            finding.rationale = "No lexically relevant approved paragraph was found."
        findings.append(finding)

    create_tracked_docx(document_path, output_path, replacements)
    report = {
        "document": str(document_path),
        "corpus": str(corpus_dir),
        "tracked_output": str(output_path),
        "configuration": configuration,
        "reference_count": len(references),
        "finding_count": len(findings),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "findings": [asdict(finding) for finding in findings],
    }
    Path(report_path).parent.mkdir(parents=True, exist_ok=True)
    Path(report_path).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def promote_document(document_path: str | Path, corpus_dir: str | Path) -> Path:
    """Add a human-approved document to the reference corpus."""
    source = Path(document_path)
    target_dir = Path(corpus_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / source.name
    shutil.copy2(source, target)
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    review_parser = subparsers.add_parser("review")
    review_parser.add_argument("--document", required=True)
    review_parser.add_argument("--corpus", default="references")
    review_parser.add_argument("--output", default="artifacts/reviewed_with_track_changes.docx")
    review_parser.add_argument("--report", default="artifacts/consistency_report.json")

    promote_parser = subparsers.add_parser("promote")
    promote_parser.add_argument("--document", required=True, help="human-approved DOCX")
    promote_parser.add_argument("--corpus", default="references")

    args = parser.parse_args()
    if args.command == "promote":
        print(f"Promoted reference: {promote_document(args.document, args.corpus)}")
        return
    report = review_document(args.document, args.corpus, args.output, args.report)
    print(f"Checked {report['finding_count']} paragraph(s) against {report['reference_count']} reference paragraph(s).")
    print(f"Tracked document: {args.output}")
    print(f"Consistency report: {args.report}")


if __name__ == "__main__":
    main()
