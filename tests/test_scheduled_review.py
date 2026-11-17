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
