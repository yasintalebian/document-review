"""ISO/IEC 27001:2022 review helpers.

The baseline file contains review anchors and organization-approved summaries.
It must not be treated as a substitute for the licensed standard or the
organization's Statement of Applicability.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass

from llm_client import LLMClient, LLMRequestError


@dataclass(frozen=True)
class ISORequirement:
    reference_id: str
    title: str
    summary: str
    keywords: list[str]
    severity: str = "medium"


@dataclass
class ISOFinding:
    reference_id: str
    title: str
    status: str
    rationale: str = ""
    suggested_text: str = ""
    target_paragraph: int | None = None
    severity: str = "medium"


def load_baseline(path: str) -> tuple[str, list[ISORequirement]]:
    with open(path, encoding="utf-8") as file:
        data = json.load(file)
    requirements = [
        ISORequirement(
            reference_id=item["reference_id"],
            title=item["title"],
            summary=item.get("summary", ""),
            keywords=item.get("keywords", []),
            severity=item.get("severity", "medium"),
        )
        for item in data.get("requirements", [])
    ]
    return data.get("standard", "ISO/IEC 27001:2022"), requirements


def _parse_json(text: str) -> dict:
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        return {}
    try:
        value = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def review_iso_document(
    client: LLMClient | None,
    paragraphs: list[str],
    requirements: list[ISORequirement],
) -> list[ISOFinding]:
    if not requirements:
        return []
    if client is None:
        return [
            ISOFinding(
                reference_id=item.reference_id,
                title=item.title,
                status="needs_evidence",
                rationale="Configure the internal LLM before running ISO conformity review.",
                severity=item.severity,
            )
            for item in requirements
        ]

    document = "\n".join(f"[{index}] {text}" for index, text in enumerate(paragraphs) if text)
    baseline = [asdict(item) for item in requirements if item.summary or item.keywords]
    if not baseline:
        return [
            ISOFinding(
                reference_id=item.reference_id,
                title=item.title,
                status="needs_evidence",
                rationale="The baseline has no approved requirement summaries or keywords.",
                severity=item.severity,
            )
            for item in requirements
        ]

    messages = [
        {
            "role": "system",
            "content": (
                "You are an ISO/IEC 27001:2022 document reviewer. Review the candidate "
                "document against the supplied organization-approved requirement anchors. "
                "Return only JSON in the form {\"findings\":[...]}. Each finding must have "
                "reference_id, status, rationale, suggested_text, target_paragraph. "
                "status must be covered, partial, gap, not_applicable, or needs_evidence. "
                "Use gap or partial only when the supplied document gives insufficient "
                "coverage. Add concise suggested_text for a gap or material partial gap. "
                "Do not claim certification and do not invent normative requirements."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {"candidate_document": document, "approved_requirement_anchors": baseline},
                ensure_ascii=False,
            ),
        },
    ]
    try:
        response = _parse_json(client.complete(messages))
    except LLMRequestError as exc:
        return [
            ISOFinding(
                reference_id=item.reference_id,
                title=item.title,
                status="needs_evidence",
                rationale=f"LLM classification failed: {exc}",
                severity=item.severity,
            )
            for item in requirements
        ]

    by_id = {item.reference_id: item for item in requirements}
    findings: list[ISOFinding] = []
    for raw in response.get("findings", []):
        reference_id = str(raw.get("reference_id", ""))
        requirement = by_id.get(reference_id)
        if requirement is None:
            continue
        target = raw.get("target_paragraph")
        try:
            target = int(target) if target is not None else None
        except (TypeError, ValueError):
            target = None
        findings.append(ISOFinding(
            reference_id=reference_id,
            title=requirement.title,
            status=str(raw.get("status", "needs_evidence")),
            rationale=str(raw.get("rationale", "")),
            suggested_text=str(raw.get("suggested_text", "")),
            target_paragraph=target,
            severity=requirement.severity,
        ))
    found_ids = {finding.reference_id for finding in findings}
    for requirement in requirements:
        if requirement.reference_id not in found_ids:
            findings.append(ISOFinding(
                reference_id=requirement.reference_id,
                title=requirement.title,
                status="needs_evidence",
                rationale="The model did not return a finding for this requirement anchor.",
                severity=requirement.severity,
            ))
    return findings
