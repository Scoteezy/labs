import unittest

import numpy as np

from lab07 import baseline


class BaselineTests(unittest.TestCase):
    def test_identical_arrays_have_zero_difference(self):
        image = np.full((128, 128), 0.5, dtype=np.float32)
        self.assertEqual(baseline.baseline_score(image, image.copy()), 0.0)

    def test_threshold_selection_uses_f1_then_recall(self):
        rows = [
            {"score": 0.1, "label": 0},
            {"score": 0.2, "label": 1},
            {"score": 0.8, "label": 1},
        ]
        threshold, result = baseline.choose_threshold(rows)
        self.assertEqual(threshold, 0.15)
        self.assertEqual(result["f1"], 1.0)


if __name__ == "__main__":
    unittest.main()
