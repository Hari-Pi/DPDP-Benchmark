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

    def test_pc_is_preferred_and_failure_falls_back_to_colab(self):
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory) / "jobs.sqlite3")
            job = store.create(question="q", history=[], k=3, model="m")

            self.assertIsNone(store.claim_next(
                "colab-1", worker_kind="colab", pc_available=True))
            claimed = store.claim_next("pc-1", worker_kind="pc")
            self.assertEqual(claimed["id"], job["id"])
            self.assertEqual(claimed["progress"], 5)

            working = store.update_progress(
                job["id"], "pc-1", progress=42,
                stage="Searching semantic matches",
            )
            self.assertEqual(working["progress"], 42)
            self.assertEqual(working["stage"], "Searching semantic matches")
            # Late/out-of-order events cannot move the bar backwards.
            self.assertEqual(store.update_progress(
                job["id"], "pc-1", progress=20, stage="Still working",
            )["progress"], 42)

            store.retry_on_colab(job["id"], "PC model unavailable")
            self.assertIsNone(store.claim_next("pc-1", worker_kind="pc"))
            fallback = store.claim_next(
                "colab-1", worker_kind="colab", pc_available=True)
            self.assertEqual(fallback["id"], job["id"])
            completed = store.complete(
                fallback["id"], answer="done", sources=[])
            self.assertEqual(completed["progress"], 100)
            self.assertEqual(completed["stage"], "Complete")

    def test_pc_disconnect_marks_job_for_colab(self):
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory) / "jobs.sqlite3")
            job = store.create(question="q", history=[], k=3, model="m")
            store.claim_next("pc-1", worker_kind="pc")
            self.assertEqual(
                store.requeue_worker("pc-1", pc_attempted=True), 1)
            self.assertIsNone(store.claim_next("pc-2", worker_kind="pc"))
            self.assertEqual(
                store.claim_next("colab-1", worker_kind="colab")["id"],
                job["id"],
            )


if __name__ == "__main__":
    unittest.main()
