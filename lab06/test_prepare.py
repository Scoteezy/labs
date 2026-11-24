"""Focused checks for the preprocessing boundary used by all later labs."""

import unittest

import numpy as np
from PIL import Image

from lab06.prepare import TARGET_SIZE, prepare_pair


class PreparePairTests(unittest.TestCase):
    def image(self, color):
        return Image.new("RGB", (24, 20), color)

    def test_returns_aligned_float_arrays(self):
        reference, candidate = prepare_pair(
            self.image((255, 0, 0)), self.image((0, 255, 0)),
            [2, 2, 22, 18], [2, 2, 22, 18],
        )
        self.assertEqual(reference.shape, TARGET_SIZE[::-1])
        self.assertEqual(candidate.shape, TARGET_SIZE[::-1])
        self.assertEqual(reference.dtype, np.float32)
        self.assertTrue(np.all((0 <= reference) & (reference <= 1)))
        self.assertFalse(np.array_equal(reference, candidate))

    def test_rejects_invalid_boxes_and_modes(self):
        image = self.image((255, 0, 0))
        with self.assertRaisesRegex(ValueError, "outside"):
            prepare_pair(image, image, [0, 0, 25, 10], [0, 0, 10, 10])
        with self.assertRaisesRegex(ValueError, "integers"):
            prepare_pair(image, image, [0, 0, 10.0, 10], [0, 0, 10, 10])
        with self.assertRaisesRegex(ValueError, "RGB"):
            prepare_pair(image.convert("L"), image, [0, 0, 10, 10], [0, 0, 10, 10])


if __name__ == "__main__":
    unittest.main()
