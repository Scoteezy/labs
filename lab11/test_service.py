"""Tests for the Lab 11 service boundary, including an external process."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import unittest
from http.client import HTTPConnection
from unittest.mock import patch

from lab11.inspect import ApiError, InspectionService, baseline, experiment
from lab11.verify import REPOSITORY, pair_payload


class InspectionServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.service = InspectionService.load()
        if cls.service.decision is None:
            raise RuntimeError(f"Selected model is unavailable: {cls.service.resource_error}")
        cls.valid = pair_payload("PAIR001_01")
        cls.critical = pair_payload("PAIR001_08")

    def test_selected_model_returns_a_designer_review_signal(self):
        output = self.service.inspect(self.valid)
        self.assertEqual(output["assessment"], "passed")
        self.assertEqual(output["mode"], "baseline")
        self.assertTrue(output["human_decision_required"])
        self.assertEqual(output["input"]["original_box"], self.valid["original_box"])

    def test_candidate_mode_is_callable_but_not_the_selected_model(self):
        output = InspectionService.load(force_mode="candidate").inspect(self.critical)
        self.assertEqual(output["mode"], "candidate")
        self.assertEqual(output["assessment"], "suspected_distortion")

    def test_bad_box_never_reaches_scoring(self):
        payload = dict(self.valid, candidate_box=[0, 0, 9999, 10])
        with self.assertRaisesRegex(ApiError, "invalid_box"):
            self.service.inspect(payload)

    def test_both_scoring_paths_can_fail_cleanly(self):
        candidate = InspectionService.load(force_mode="candidate")
        with (patch.object(experiment, "candidate_score", return_value=float("nan")),
              patch.object(baseline, "baseline_score", side_effect=ValueError("fixture")),
              self.assertRaisesRegex(ApiError, "model_unavailable") as error):
            candidate.inspect(self.critical)
        self.assertEqual(error.exception.status, 503)

    def test_server_runs_in_a_separate_process(self):
        process = subprocess.Popen(
            [sys.executable, "-m", "lab11.server", "--port", "0"],
            cwd=REPOSITORY,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            line = process.stdout.readline() if process.stdout else ""
            match = re.fullmatch(r"Listening on http://127\.0\.0\.1:(\d+)\n?", line)
            if not match:
                stderr = process.stderr.read() if process.stderr else ""
                self.fail(f"Server did not start: {line!r}; stderr={stderr!r}")
            body = json.dumps(self.valid, separators=(",", ":")).encode("utf-8")
            connection = HTTPConnection("127.0.0.1", int(match.group(1)), timeout=5)
            try:
                connection.request("POST", "/inspect", body=body, headers={"Content-Type": "application/json"})
                response = connection.getresponse()
                output = json.loads(response.read())
            finally:
                connection.close()
            self.assertEqual(response.status, 200)
            self.assertEqual(output["assessment"], "passed")
        finally:
            process.terminate()
            process.wait(timeout=5)
            if process.stdout:
                process.stdout.close()
            if process.stderr:
                process.stderr.close()


if __name__ == "__main__":
    unittest.main()
