import json
from argparse import Namespace
from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import unittest
from zoneinfo import ZoneInfo

from docx import Document

from scheduled_review import run, load_state
from tests.test_editorial_review import FakeClient, fixture

TZ = ZoneInfo("Asia/Tehran")
SATURDAY = datetime(2026, 11, 21, 8, tzinfo=TZ)
THURSDAY = datetime(2026, 11, 19, 8, tzinfo=TZ)


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.library, self.outbox = root / "references", root / "outbox"
        self.library.mkdir(); self.outbox.mkdir()
        for name in ("SMIA.RG.01.Ver1.0", "SMIA.RG.02.Ver1.0", "SMIA.RG.03.Ver1.0"):
            fixture(self.library / f"{name}.docx")
        (self.library / "~$SMIA.RG.01.Ver1.0.docx").write_bytes(b"word lock file")
        self.args = Namespace(library=str(self.library), outbox=str(self.outbox), state=str(root / "state.json"),
                              artifacts=str(root / "artifacts"), per_run=2, interval_days=365, retry_days=7,
                              max_extra_attempts=5, check=False, dry_run=False, force=False)

    def tearDown(self):
        self.temp.cleanup()

    def packages(self):
        return sorted(json.loads((p / "manifest.json").read_text())["source_filename"]
                      for p in self.outbox.iterdir() if not p.name.startswith("."))

    def state(self):
        return load_state(Path(self.args.state))["documents"]

    def test_two_per_run_oldest_first_then_wait_a_year(self):
        self.assertEqual(run(self.args, FakeClient(), SATURDAY), 0)
        self.assertEqual(self.packages(), ["SMIA.RG.01.Ver1.0.docx", "SMIA.RG.02.Ver1.0.docx"])
        run(self.args, FakeClient(), SATURDAY + timedelta(days=1))
        self.assertEqual(len(self.packages()), 3)
        run(self.args, FakeClient(), SATURDAY + timedelta(days=2))
        self.assertEqual(len(self.packages()), 3)  # everything reviewed; nothing due for a year
        run(self.args, FakeClient(), SATURDAY + timedelta(days=366))
        self.assertEqual(len(self.packages()), 5)  # the two oldest come round again
        self.assertNotIn("~$SMIA.RG.01.Ver1.0.docx", self.state())

    def test_published_package_keeps_original_name_and_tracked_changes(self):
        run(self.args, FakeClient(), SATURDAY)
        entry = self.state()["SMIA.RG.01.Ver1.0.docx"]
        package = self.outbox / entry["run_id"]
        self.assertTrue((package / "SMIA.RG.01.Ver1.0.docx").exists())
        manifest = json.loads((package / "manifest.json").read_text())
        self.assertEqual(manifest["title"], "SMIA.RG.01.Ver1.0")
        self.assertEqual(entry["changes"], 4)

    def test_no_run_on_thursday_unless_forced(self):
        run(self.args, FakeClient(), THURSDAY)
        self.assertEqual(self.packages(), [])
        self.args.force = True
        run(self.args, FakeClient(), THURSDAY)
        self.assertEqual(len(self.packages()), 2)

    def test_bad_document_is_skipped_recorded_and_retried_later(self):
        d = Document(); d.add_paragraph("سند بدون تاریخ"); d.save(self.library / "SMIA.RG.00.Ver1.0.docx")
        run(self.args, FakeClient(), SATURDAY)
        self.assertEqual(self.packages(), ["SMIA.RG.01.Ver1.0.docx", "SMIA.RG.02.Ver1.0.docx"])
        bad = self.state()["SMIA.RG.00.Ver1.0.docx"]
        self.assertIn("پیدا نشد", bad["last_error"]); self.assertEqual(bad["failures"], 1)
        run(self.args, FakeClient(), SATURDAY + timedelta(days=1))
        self.assertEqual(self.state()["SMIA.RG.00.Ver1.0.docx"]["failures"], 1)  # not retried within 7 days
        fixture(self.library / "SMIA.RG.00.Ver1.0.docx")  # fixed file -> retried at once
        run(self.args, FakeClient(), SATURDAY + timedelta(days=2))
        self.assertIn("SMIA.RG.00.Ver1.0.docx", self.packages())

    def test_many_broken_documents_do_not_reduce_daily_quota(self):
        for i in range(7):
            d = Document(); d.add_paragraph("بدون قالب"); d.save(self.library / f"AAA.broken.{i}.docx")
        run(self.args, FakeClient(), SATURDAY)
        self.assertEqual(len(self.packages()), 2)
        self.assertEqual(sum(1 for k, e in self.state().items() if k.startswith("AAA") and e.get("failures")), 7)

    def test_llm_outage_stops_without_blaming_documents(self):
        from llm_client import LLMRequestError

        class Down:
            def complete(self, messages):
                raise LLMRequestError("timed out")
        self.assertEqual(run(self.args, Down(), SATURDAY), 3)
        self.assertEqual(self.packages(), [])
        self.assertFalse(any(e.get("last_failed") for e in self.state().values()))

    def test_check_and_dry_run_change_nothing(self):
        d = Document(); d.add_paragraph("سند بدون تاریخ"); d.save(self.library / "broken.docx")
        self.args.check = True
        self.assertEqual(run(self.args, FakeClient(), SATURDAY), 1)
        self.args.check = False; self.args.dry_run = True
        self.assertEqual(run(self.args, FakeClient(), THURSDAY), 0)
        self.assertEqual(self.packages(), [])
        self.assertFalse(Path(self.args.state).exists())


if __name__ == "__main__":
    unittest.main()


class NestedLibraryTests(unittest.TestCase):
    """The real library: references/docs/<one folder per document>/<code>.docx plus PDFs, Excel and lock files."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.library, self.outbox = root / "references", root / "outbox"
        self.outbox.mkdir()
        net = self.library / "docs" / "امنیت شبکه"; net.mkdir(parents=True)
        fixture(net / "SMIA.RG.13.Ver02.6.docx")
        (net / "SMIA.RG.13.Ver02.6.pdf").write_bytes(b"%PDF")
        (net / "~$IA.RG.13.Ver02.6.docx").write_bytes(b"lock")
        hard = self.library / "docs" / "هاردنینگ" / "ویندوز"; hard.mkdir(parents=True)
        fixture(hard / "SMIA.WI.01.Ver01.00.docx")
        (self.library / "docs" / "اهداف").mkdir()
        (self.library / "docs" / "اهداف" / "SMIA.FR.05.Ver04.5.xlsx").write_bytes(b"xlsx")
        (self.library / "docs" / "اهداف" / "old.doc").write_bytes(b"doc")
        self.args = Namespace(library=str(self.library), outbox=str(self.outbox), state=str(root / "state.json"),
                              artifacts=str(root / "artifacts"), per_run=2, interval_days=365, retry_days=7,
                              max_extra_attempts=5, check=False, dry_run=False, force=False)

    def tearDown(self):
        self.temp.cleanup()

    def test_reviews_documents_in_subfolders_and_reports_their_path(self):
        self.assertEqual(run(self.args, FakeClient(), SATURDAY), 0)
        manifests = [json.loads((p / "manifest.json").read_text()) for p in self.outbox.iterdir()
                     if not p.name.startswith(".")]
        self.assertEqual(sorted(m["library_path"] for m in manifests),
                         ["docs/امنیت شبکه/SMIA.RG.13.Ver02.6.docx", "docs/هاردنینگ/ویندوز/SMIA.WI.01.Ver01.00.docx"])
        self.assertEqual(sorted(m["source_filename"] for m in manifests),
                         ["SMIA.RG.13.Ver02.6.docx", "SMIA.WI.01.Ver01.00.docx"])
        self.assertEqual(sorted(load_state(Path(self.args.state))["documents"]),
                         ["docs/امنیت شبکه/SMIA.RG.13.Ver02.6.docx", "docs/هاردنینگ/ویندوز/SMIA.WI.01.Ver01.00.docx"])

    def test_check_lists_skipped_files(self):
        import io
        from contextlib import redirect_stdout
        self.args.check = True
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(run(self.args, FakeClient(), SATURDAY), 0)
        text = out.getvalue()
        self.assertIn("OK  docs/امنیت شبکه/SMIA.RG.13.Ver02.6.docx", text)
        self.assertIn("SKIP 1 .pdf", text); self.assertIn("SKIP 1 .xlsx", text); self.assertIn("SKIP 1 lock/temp", text)
        self.assertIn("SKIP 1 .doc file(s) — not reviewed: docs/اهداف/old.doc", text)
        self.assertIn("2 document(s), 2 ready, 0 need fixing", text)
