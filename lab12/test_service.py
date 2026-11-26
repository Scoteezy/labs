"""Regression checks for the rules, repeated decisions, and concurrent storage."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from lab11.inspect import ApiError
from lab12.service import ReviewService
from lab12.verify import CONTEXT


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "review.sqlite"
        self.service = ReviewService(self.path)

    def inspect(self, record_id="PAIR001_01", context=None):
        return self.service.inspect({"record_id": record_id, "context": context or CONTEXT})

    def feedback(self, item, **changes):
        return {
            "event_id": "E_test", "inspection_id": item["inspection_id"],
            "actor": "designer_demo", "action": "accept", "note": "Упаковка проверена",
            **changes,
        }

    def test_failed_precondition_bypasses_model_and_blocks_acceptance(self):
        with patch.object(self.service.detector, "inspect", side_effect=AssertionError("Model should not run")):
            item = self.inspect(context={**CONTEXT, "frontal_view": False})
        self.assertEqual(item["assessment"], "manual_review")
        self.assertIn("frontal_view_not_confirmed", item["reasons"])
        with self.assertRaisesRegex(ApiError, "expert_review_required"):
            self.service.feedback(self.feedback(item))
        self.assertEqual(self.service.store.events(), [])

    def test_repeated_event_and_restart_preserve_one_decision(self):
        item = self.inspect()
        request = self.feedback(item)
        first = self.service.feedback(request)
        reopened = ReviewService(self.path)
        self.assertEqual(first, reopened.feedback(request))
        self.assertEqual(len(reopened.store.events()), 1)
        self.assertTrue(reopened.store.get(item["inspection_id"])["release_allowed"])

    def test_concurrent_services_cannot_make_two_final_decisions(self):
        item = self.inspect()
        other = ReviewService(self.path)

        def decide(service, event_id, action):
            try:
                service.feedback(self.feedback(item, event_id=event_id, action=action))
                return 200
            except ApiError as error:
                return error.status

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(decide, self.service, "E_accept", "accept"),
                executor.submit(decide, other, "E_reject", "reject"),
            ]
            self.assertEqual(sorted(f.result() for f in futures), [200, 409])
        self.assertEqual(len(self.service.store.events()), 1)

    def test_correction_changes_workflow_but_not_machine_assessment(self):
        before = self.inspect("PAIR019_04")
        self.service.feedback(self.feedback(
            before, action="correct", proposed_label=0, defect_type="none",
        ))
        after = self.inspect("PAIR019_04")
        self.assertEqual(after["assessment"], before["assessment"])
        self.assertEqual(after["machine_result"], before["machine_result"])
        self.assertEqual(after["review_status"], "awaiting_expert")
        self.assertFalse(after["release_allowed"])
        self.assertFalse(after["feedback"]["dataset_updated"])
        self.assertFalse(after["feedback"]["model_updated"])

    def test_catalog_ground_truth_does_not_feed_detector(self):
        first = self.inspect("PAIR001_08")
        self.service.records["PAIR001_08"]["label"] = 0
        self.service.records["PAIR001_08"]["defect_type"] = "none"
        second = self.inspect("PAIR001_08")
        self.assertEqual(first["machine_result"], second["machine_result"])

    def test_image_hash_failure_prevents_inspection(self):
        self.service.records["PAIR001_01"]["candidate_sha256"] = "0" * 64
        with self.assertRaisesRegex(ApiError, "image_integrity_failed"):
            self.inspect()

    def test_note_and_correction_fields_are_validated_before_storage(self):
        item = self.inspect()
        for changes, code in (
            ({"note": " "}, "note_must_have_1_to_500_chars"),
            ({"note": "я" * 501}, "note_must_have_1_to_500_chars"),
            ({"action": "correct", "proposed_label": True, "defect_type": "text"}, "invalid_label_and_defect_type"),
            ({"proposed_label": 0, "defect_type": "none"}, "correction_fields_require_correct"),
        ):
            with self.subTest(code=code), self.assertRaisesRegex(ApiError, code):
                self.service.feedback(self.feedback(item, **changes))
        self.assertEqual(self.service.store.events(), [])


if __name__ == "__main__":
    unittest.main()
