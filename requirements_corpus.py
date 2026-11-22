"""Requirements documents (e.g. AFTA or another authority) used during the editorial review.

Files in the requirements folder (.docx, .pdf, .txt) are split into short clauses. For each batch
of document paragraphs the most relevant clauses are chosen by word overlap (no external service,
works offline) and given to the model, which may then align a paragraph with a cited clause.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import math
from pathlib import Path
import re

TYPES = (".docx", ".pdf", ".txt")
CHUNK_CHARS = 700
_TOKEN = re.compile(r"[\w؀-ۿ]+")
_STOP = set("""و در به از که این را با برای است یا آن ها های می شود باید بر تا هر نیز شده کند کنند گردد
گیرد نماید باشد باشند بین پس اگر هم یک دو سه اما ولی چه چون نه بی مورد بوده خود آنها انجام the and of to in
for a is be on or by with as are that this""".split())


@dataclass
class Clause:
    id: str
    source: str
    text: str


def normalize(text: str) -> str:
    text = text.replace("ي", "ی").replace("ك", "ک").replace("‌", " ").replace("‏", "").replace("‎", "")
    text = re.sub(r"[ً-ْ]", "", text)  # Arabic diacritics
    return text.lower()


def tokens(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(normalize(text)) if len(t) > 2 and t not in _STOP and not t.isdigit()]


def _docx_text(path: Path) -> list[str]:
    import docx
    d = docx.Document(str(path))
    parts = [p.text for p in d.paragraphs]
    for table in d.tables:
        for row in table.rows:
            cells = []
            for cell in row.cells:
                if cell.text.strip() and cell.text not in cells:
                    cells.append(cell.text.strip())
            parts.append(" | ".join(cells))
    return parts


def _pdf_text(path: Path) -> list[str]:
    from pypdf import PdfReader  # optional dependency; a missing package is reported as a warning
    return [line for page in PdfReader(str(path)).pages for line in (page.extract_text() or "").splitlines()]


def _chunks(lines: list[str]) -> list[str]:
    out, current = [], ""
    for line in (re.sub(r"\s+", " ", l).strip() for l in lines):
        if not line:
            continue
        if current and len(current) + len(line) > CHUNK_CHARS:
            out.append(current)
            current = ""
        current = f"{current} {line}".strip()
        while len(current) > CHUNK_CHARS * 2:
            out.append(current[:CHUNK_CHARS * 2])
            current = current[CHUNK_CHARS * 2:]
    if current:
        out.append(current)
    return out


def load(folder) -> tuple[list[Clause], list[str]]:
    """(clauses, warnings) from every requirements file directly in the folder."""
    folder = Path(folder) if folder else None
    clauses, warnings = [], []
    if not folder or not folder.is_dir():
        return clauses, warnings
    for path in sorted(p for p in folder.iterdir() if p.is_file() and not p.name.startswith((".", "~$"))):
        if path.suffix.lower() not in TYPES:
            continue
        try:
            if path.suffix.lower() == ".docx":
                lines = _docx_text(path)
            elif path.suffix.lower() == ".pdf":
                lines = _pdf_text(path)
            else:
                lines = path.read_text(encoding="utf-8-sig").splitlines()
        except ImportError:
            warnings.append(f"خواندن PDF ممکن نشد (کتابخانهٔ pypdf نصب نیست): {path.name}")
            continue
        except Exception as exc:  # a broken file must not stop the review
            warnings.append(f"سند الزام خوانده نشد ({exc.__class__.__name__}): {path.name}")
            continue
        texts = _chunks(lines)
        if not texts:
            warnings.append(f"متنی در سند الزام یافت نشد (احتمالاً PDF اسکن‌شده): {path.name}")
        for i, text in enumerate(texts, 1):
            clauses.append(Clause(f"R{len(clauses) + 1}", path.name, text))
    return clauses, warnings


class Index:
    """Word-overlap relevance (TF-IDF-like) between document text and requirement clauses."""

    def __init__(self, clauses: list[Clause]):
        self.clauses = clauses
        self.terms = [Counter(tokens(c.text)) for c in clauses]
        df = Counter(t for terms in self.terms for t in terms)
        n = max(len(clauses), 1)
        self.idf = {t: math.log(1 + n / f) for t, f in df.items()}

    def rank(self, text: str, limit: int, among: list[Clause] | None = None, min_score: float = 1.5) -> list[Clause]:
        query = set(tokens(text))
        if not query:
            return []
        pool = among if among is not None else self.clauses
        position = {id(c): i for i, c in enumerate(self.clauses)}
        scored = []
        for clause in pool:
            terms = self.terms[position[id(clause)]]
            overlap = query & terms.keys()
            score = sum(self.idf[t] for t in overlap) / math.sqrt(1 + len(terms) / 40)
            if score >= min_score and len(overlap) >= 2:
                scored.append((score, clause))
        scored.sort(key=lambda sc: -sc[0])
        return [c for _, c in scored[:limit]]
