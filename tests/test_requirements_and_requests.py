import hashlib
import json
from argparse import Namespace
from datetime import timedelta
from pathlib import Path
import tempfile
import unittest

from docx import Document

from editorial_review import GAP_SYSTEM, review
from requirements_corpus import Index, load
from tests.test_editorial_review import NOW, NS, FakeClient, accepted, fixture, xml

REQUIREMENT = "طول کلمه عبور در متن آزمایشی باید حداقل 14 کاراکتر باشد و این الزام برای همه لازم است."
UNRELATED = "پشتیبان‌گیری از پایگاه داده باید روزانه انجام و در محل امن نگهداری شود."


class RequirementClient(FakeClient):
    """Copy-edits like FakeClient; with requirements it raises 13 -> 14 citing the clause; answers gap checks."""
    def __init__(self, new_number="14", gap_text="لازم است پشتیبان‌گیری روزانه انجام و در محل امن نگهداری شود."):
        self.new_number = new_number
        self.gap_text = gap_text
        self.gap_calls = 0

    def complete(self, messages):
        if messages[0]["content"] == GAP_SYSTEM:
            self.gap_calls += 1
            data = json.loads(messages[1]["content"])
            cand = next((c for c in data["candidates"] if "پشتیبان" in c["clause"]), None)
            if cand is None or not cand["closest_paragraphs"]:
                return json.dumps({"gaps": []})
            anchor = cand["closest_paragraphs"][-1]["paragraph_id"]
            return json.dumps({"gaps": [{"requirement_id": cand["requirement_id"], "issue": "روال پشتیبان‌گیری در سند نیامده است",
                                         "text": self.gap_text, "insert_after": anchor}]},
                              ensure_ascii=False)
        data = json.loads(messages[1]["content"])
        reqs = data.get("requirements") or []
        edits = []
        for p in data["paragraphs"]:
            if "ميباشد" in p["text"]:
                after = p["text"].replace("ميباشد", "می‌باشد")
                edit = {"paragraph_id": p["paragraph_id"], "after": after, "reason": "اصلاح نویسه"}
                if reqs:
                    edit.update(after=after.replace("13", self.new_number), requirement_id=reqs[0]["id"],
                                reason="مطابق الزام حداقل طول کلمه عبور")
                edits.append(edit)
        return json.dumps({"edits": edits}, ensure_ascii=False)


class RequirementsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.reqdir = self.root / "requirements"; self.reqdir.mkdir()
        d = Document(); d.add_paragraph("الزامات افتا"); d.add_paragraph(REQUIREMENT); d.save(self.reqdir / "afta.docx")
        (self.reqdir / "backup.txt").write_text(UNRELATED, encoding="utf-8")
        (self.reqdir / "notes.xlsx").write_bytes(b"ignored")
        self.src = self.root / "SMIA.RG.17.Ver2.05.docx"; fixture(self.src)

    def tearDown(self): self.temp.cleanup()

    def test_load_and_rank(self):
        clauses, warnings = load(self.reqdir)
        self.assertEqual(sorted({c.source for c in clauses}), ["afta.docx", "backup.txt"])
        self.assertEqual(warnings, [])
        best = Index(clauses).rank("حداقل 13 کاراکتر کلمه عبور لازم است", limit=1)
        self.assertEqual(best[0].source, "afta.docx")

    def test_synonyms_and_context_find_the_right_clause(self):
        from requirements_corpus import Clause
        clauses = [Clause("R1", "afta.pdf", "برای کاربران عادی یک گذرواژه حداقل باید ۸ کاراکتر و برای مدیران حداقل ۱۳ کاراکتر باشد."),
                   Clause("R2", "afta.pdf", "انقضای سیستمی گذرواژه‌ها برای مدیران یک ماه و برای کاربران عادی سه ماه باشد."),
                   Clause("R3", "afta.pdf", "قفل شدن حساب کاربری پس از سه بار تلاش ناموفق برای ورود به سامانه."),
                   Clause("R4", "afta.pdf", "اهداف: حفاظت از نام کاربری و گذرواژه در سطح کاربر و سامانه‌های مرتبط.")]
        index = Index(clauses)
        heading = "الزامات مرتبط با شناسه‌های کاربری سطح ادمین مشخصات کلمه عبور راهبر سامانه"
        length = index.scored("لازم است حداقل 8 کاراکتر باشد.", 1, min_score=1.0, context=heading)
        self.assertEqual(length[0][1].id, "R1")
        expiry = index.scored("زمان انقضای کلمه عبور حداکثر شش ماه در نظر گرفته شود.", 1, min_score=1.0, context=heading)
        self.assertEqual(expiry[0][1].id, "R2")

    def test_scanned_pdf_uses_ocr_text(self):
        from pypdf import PdfWriter
        w = PdfWriter(); w.add_blank_page(595, 842)
        with open(self.reqdir / "afta-scan.pdf", "wb") as fh:
            w.write(fh)
        _, warnings = load(self.reqdir)
        self.assertTrue(any("afta-scan.pdf" in x and "OCR" in x for x in warnings))
        (self.reqdir / "afta-scan.pdf.ocr.txt").write_text(
            "حداقل طول گذرواژه در سامانه‌ها باید ۱۳ کاراکتر باشد.", encoding="utf-8")
        clauses, warnings = load(self.reqdir)
        self.assertEqual(warnings, [])
        scan = [c for c in clauses if c.source == "afta-scan.pdf"]
        self.assertEqual(len(scan), 1); self.assertIn("۱۳", scan[0].text)
        self.assertNotIn("afta-scan.pdf.ocr.txt", {c.source for c in clauses})

    def test_requirement_edit_applied_in_place_and_cited(self):
        clauses, _ = load(self.reqdir)
        client = RequirementClient()
        report = review(self.src, self.root / "out", client, now=NOW, requirements=clauses)
        text = accepted(xml(self.root / "out" / self.src.name))
        self.assertIn("حداقل 14 کاراکتر", text)
        req = [f for f in report["findings"] if f["kind"] == "requirement"]
        self.assertEqual(len(req), 1)
        self.assertEqual(req[0]["requirement"]["source"], "afta.docx")
        self.assertIn("الزام: afta.docx", req[0]["issue"])
        self.assertEqual(report["summary"]["requirement_changes"], 1)
        self.assertIn("afta.docx", report["requirements_used"])

    def test_number_not_in_requirement_is_rejected(self):
        clauses, _ = load(self.reqdir)
        report = review(self.src, self.root / "out", RequirementClient(new_number="99"), now=NOW, requirements=clauses)
        self.assertIn("حداقل 13 کاراکتر", accepted(xml(self.root / "out" / self.src.name)))
        self.assertTrue(any("در الزام" in r["reason_rejected"] for r in report["rejected_suggestions"]))

    def _gap_setup(self):
        (self.reqdir / "backup.txt").write_text("در متن آزمایشی حداقل یک روال پشتیبان‌گیری روزانه لازم است.",
                                                encoding="utf-8")
        clauses, _ = load(self.reqdir)
        return clauses

    def test_missing_requirement_is_inserted_as_tracked_paragraph(self):
        clauses = self._gap_setup()
        client = RequirementClient()
        before_paragraphs = len(xml(self.src).xpath('.//w:p', namespaces=NS))
        report = review(self.src, self.root / "out", client, now=NOW, requirements=clauses)
        gaps = [f for f in report["findings"] if f["kind"] == "requirement_gap"]
        self.assertEqual(client.gap_calls, 1)
        self.assertEqual(len(gaps), 1); self.assertTrue(gaps[0]["applied"])
        self.assertIn("پاراگراف جدید", gaps[0]["location"])
        out = xml(self.root / "out" / self.src.name)
        self.assertEqual(len(out.xpath('.//w:p', namespaces=NS)), before_paragraphs + 1)
        new_p = [p for p in out.xpath('.//w:p', namespaces=NS) if "پشتیبان‌گیری روزانه" in "".join(p.itertext())][0]
        self.assertTrue(new_p.xpath('./w:pPr/w:rPr/w:ins', namespaces=NS))  # paragraph mark is tracked
        self.assertTrue(new_p.xpath('./w:ins/w:r/w:t', namespaces=NS))       # text is tracked
        self.assertFalse(new_p.xpath('.//w:sectPr', namespaces=NS))
        self.assertIn("پشتیبان‌گیری روزانه", accepted(out))
        self.assertEqual(report["summary"]["requirement_gaps_added"], 1)
        self.assertIn("افزوده شد:", (self.root / "out" / "report.txt").read_text(encoding="utf-8"))

    def test_gap_with_invented_number_is_only_reported(self):
        clauses = self._gap_setup()
        client = RequirementClient(gap_text="لازم است پشتیبان‌گیری هر 6 ساعت انجام و در محل امن نگهداری شود.")
        before_paragraphs = len(xml(self.src).xpath('.//w:p', namespaces=NS))
        report = review(self.src, self.root / "out", client, now=NOW, requirements=clauses)
        gap = [f for f in report["findings"] if f["kind"] == "requirement_gap"][0]
        self.assertFalse(gap["applied"]); self.assertIn("در الزام نیامده", gap["not_applied_reason"])
        self.assertEqual(len(xml(self.root / "out" / self.src.name).xpath('.//w:p', namespaces=NS)), before_paragraphs)
        self.assertIn("افزوده نشد", (self.root / "out" / "report.txt").read_text(encoding="utf-8"))

    def test_no_requirements_means_no_extra_calls(self):
        client = RequirementClient()
        report = review(self.src, self.root / "out", client, now=NOW)
        self.assertEqual(client.gap_calls, 0)
        self.assertEqual(report["requirements_used"], [])


def make_request(requests: Path, code: str, mode: str, src: Path, title: str):
    folder = requests / code; folder.mkdir(parents=True)
    data = src.read_bytes(); (folder / src.name).write_bytes(data)
    payload = {"request_id": code, "mode": mode, "title": title, "filename": src.name,
               "library_path": f"docs/{title}/{src.name}" if mode == "library" else None,
               "sha256": hashlib.sha256(data).hexdigest()}
    (folder / "request.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return folder


class RequestProcessingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.requests, self.outbox = self.root / "requests", self.root / "outbox"
        self.requests.mkdir(); self.outbox.mkdir()
        self.args = Namespace(requests=str(self.requests), outbox=str(self.outbox), requirements=str(self.root / "none"),
                              artifacts=str(self.root / "artifacts"), state=str(self.root / "request_reviews.json"),
                              settle=0)

    def tearDown(self): self.temp.cleanup()

    def manifests(self):
        return {json.loads((p / "manifest.json").read_text())["request_id"]: json.loads((p / "manifest.json").read_text())
                for p in self.outbox.iterdir() if not p.name.startswith(".")}

    def test_library_and_one_time_requests(self):
        from request_review import run
        src = self.root / "SMIA.RG.50.Ver01.00.docx"; fixture(src)
        plain = self.root / "گزارش پیمانکار.docx"
        d = Document(); d.add_paragraph("این گزارش آزمایشی پیمانکار ميباشد و باید بررسی شود."); d.save(plain)
        make_request(self.requests, "REQ-20261122-100000-aaaaaa", "library", src, "خط مشی امنیت ایمیل")
        make_request(self.requests, "REQ-20261122-100001-bbbbbb", "one_time", plain, "گزارش پیمانکار")
        self.assertEqual(run(self.args, FakeClient(), NOW), 0)
        m = self.manifests()
        lib, once = m["REQ-20261122-100000-aaaaaa"], m["REQ-20261122-100001-bbbbbb"]
        self.assertEqual(lib["library_path"], "docs/خط مشی امنیت ایمیل/SMIA.RG.50.Ver01.00.docx")
        self.assertEqual(lib["review_mode"], "library")
        self.assertEqual(once["review_mode"], "one_time"); self.assertNotIn("library_path", once)
        self.assertEqual(once["title"], "گزارش پیمانکار")
        status = json.loads((self.requests / "REQ-20261122-100001-bbbbbb" / "status.json").read_text())
        self.assertEqual(status["state"], "published"); self.assertIn("فقط بازنگری نگارشی", status["message"])
        ledger = json.loads(Path(self.args.state).read_text())
        self.assertEqual(list(ledger), ["docs/خط مشی امنیت ایمیل/SMIA.RG.50.Ver01.00.docx"])
        self.assertEqual(run(self.args, FakeClient(), NOW), 0)  # already published: nothing resent
        self.assertEqual(len(self.manifests()), 2)

    def test_bad_request_fails_and_llm_outage_retries(self):
        from llm_client import LLMRequestError
        from request_review import run
        src = self.root / "SMIA.RG.51.Ver01.00.docx"; fixture(src)
        folder = make_request(self.requests, "REQ-20261122-100002-cccccc", "one_time", src, "x")
        (folder / src.name).write_bytes(b"tampered")
        bad = make_request(self.requests, "REQ-20261122-100003-dddddd", "library", src, "y")

        class Down:
            def complete(self, messages): raise LLMRequestError("timed out")
        self.assertEqual(run(self.args, Down(), NOW), 3)
        self.assertEqual(json.loads((folder / "status.json").read_text())["state"], "failed")
        self.assertEqual(json.loads((bad / "status.json").read_text())["state"], "queued")
        self.assertEqual(run(self.args, FakeClient(), NOW), 0)
        self.assertEqual(json.loads((bad / "status.json").read_text())["state"], "published")

    def test_scheduler_waits_a_year_after_panel_review(self):
        from scheduled_review import due_documents
        lib = self.root / "references"; f = lib / "docs" / "خط مشی امنیت ایمیل" / "SMIA.RG.50.Ver01.00.docx"
        f.parent.mkdir(parents=True); fixture(f)
        panel = {"docs/خط مشی امنیت ایمیل/SMIA.RG.50.Ver01.00.docx": NOW.isoformat()}
        due, waiting = due_documents([f], {"documents": {}}, NOW + timedelta(days=10), 365, 7, lib, panel)
        self.assertEqual(due, []); self.assertEqual(len(waiting), 1)
        due, _ = due_documents([f], {"documents": {}}, NOW + timedelta(days=366), 365, 7, lib, panel)
        self.assertEqual(due, [f])


if __name__ == "__main__":
    unittest.main()
