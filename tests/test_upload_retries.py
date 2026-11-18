import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import app as server
from jh import uploads


class UploadRetryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.materials = self.root / "materials"
        self.materials.mkdir()
        for attribute, value in [("material_root", self.materials), ("data_root", self.root / "data")]:
            replacement = patch.object(server.config, attribute, return_value=value)
            replacement.start()
            self.addCleanup(replacement.stop)
        self.client = TestClient(server.app)
        self.client.post("/api/batches", json={"name": "原项目"}).raise_for_status()
        self.client.post("/api/batches", json={"name": "另一个项目"}).raise_for_status()

    def upload(self, batch="原项目", upload_id="queue-item", body=b"video", expected=5):
        return self.client.put(f"/api/batches/{batch}/upload", content=body,
                               params={"filename": "素材.mp4", "upload_id": upload_id, "expected_size": expected})

    def test_retry_after_lost_response_returns_the_same_file_and_stays_in_original_project(self):
        first = self.upload()
        retry = self.upload()
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json(), retry.json())
        self.assertEqual([p.name for p in (self.materials / "原项目").iterdir()], ["素材.mp4"])
        self.assertEqual(list((self.materials / "另一个项目").iterdir()), [])

    def test_partial_file_is_not_published_and_can_be_retried(self):
        failed = self.upload(body=b"vi")
        self.assertEqual(failed.status_code, 400)
        self.assertIn("不完整", failed.json()["detail"])
        self.assertEqual(list((self.materials / "原项目").iterdir()), [])
        self.assertEqual(self.upload().status_code, 200)
        self.assertEqual((self.materials / "原项目" / "素材.mp4").read_bytes(), b"video")

    def test_same_queue_id_is_scoped_to_each_project_and_new_items_keep_existing_files(self):
        self.assertEqual(self.upload().status_code, 200)
        self.assertEqual(self.upload(batch="另一个项目", body=b"other").status_code, 200)
        self.assertEqual(self.upload(upload_id="different-item", body=b"newer").json()["clip"], "素材_2.mp4")
        self.assertEqual((self.materials / "原项目" / "素材.mp4").read_bytes(), b"video")
        self.assertEqual((self.materials / "另一个项目" / "素材.mp4").read_bytes(), b"other")

    def test_mismatched_retry_is_rejected_and_deleted_upload_can_be_uploaded_again(self):
        self.upload().raise_for_status()
        self.assertEqual(self.upload(body=b"different", expected=9).status_code, 409)
        target = self.materials / "原项目" / "素材.mp4"
        target.unlink()
        self.assertEqual(self.upload().status_code, 200)
        self.assertEqual(target.read_bytes(), b"video")

    def test_disconnect_cleans_up_and_concurrent_retries_do_not_duplicate(self):
        async def check():
            folder = self.materials / "原项目"
            async def interrupted():
                yield b"vi"
                raise ConnectionResetError("network disconnected")
            with self.assertRaises(ConnectionResetError):
                await uploads.receive(folder, self.root / "data", "素材.mp4", interrupted(),
                                      upload_id="retry", expected_size=5)
            self.assertEqual(list(folder.iterdir()), [])
            consumed = []
            async def body(label):
                consumed.append(label)
                yield b"vi"
                await asyncio.sleep(0)
                yield b"deo"
            results = await asyncio.gather(*[
                uploads.receive(folder, self.root / "data", "素材.mp4", body(label),
                                upload_id="retry", expected_size=5) for label in (1, 2)])
            self.assertEqual(results[0], results[1])
            self.assertEqual(consumed, [1])
            self.assertEqual(len(list(folder.iterdir())), 1)
        asyncio.run(check())

    def test_deleting_a_project_also_removes_its_upload_receipts(self):
        self.upload().raise_for_status()
        receipts = self.root / "data" / "upload_receipts" / "原项目"
        self.assertTrue(receipts.exists())
        self.assertEqual(self.client.delete("/api/batches/原项目").status_code, 200)
        self.assertFalse(receipts.exists())


if __name__ == "__main__":
    unittest.main()
