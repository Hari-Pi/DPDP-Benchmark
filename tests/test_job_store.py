import tempfile
import unittest
from pathlib import Path

from dpdp_rag.job_store import JobStore


class JobStoreTests(unittest.TestCase):
    def test_create_get_cancel_survives_reopen(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "jobs.sqlite3"
            first = JobStore(path)
            created = first.create(
                question="What is section 8?", history=[], k=8, model="test"
            )
            self.assertEqual(created["status"], "queued")
            self.assertEqual(first.counts(), {"queued": 1})

            reopened = JobStore(path)
            loaded = reopened.get(created["job_id"] if "job_id" in created else created["id"])
            self.assertIsNotNone(loaded)
            cancelled = reopened.cancel(loaded["id"])
            self.assertEqual(cancelled["status"], "cancelled")
            self.assertEqual(reopened.counts(), {"cancelled": 1})


if __name__ == "__main__":
    unittest.main()
