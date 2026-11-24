import unittest

import numpy as np

from lab09 import experiment


class CandidateTests(unittest.TestCase):
    def test_candidate_score_is_bounded(self):
        reference = np.zeros((128, 128), dtype=np.float32)
        candidate = np.ones((128, 128), dtype=np.float32)
        self.assertGreaterEqual(experiment.candidate_score(reference, candidate), 0.0)
        self.assertLessEqual(experiment.candidate_score(reference, candidate), 1.0)

    def test_deployment_decision_has_only_supported_mode(self):
        _, decision = experiment.report()
        self.assertIn(decision["mode"], ("baseline", "candidate"))
        self.assertEqual(decision["selection_split"], "validation")


if __name__ == "__main__":
    unittest.main()
