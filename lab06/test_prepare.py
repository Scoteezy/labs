"""Regression tests for annotation boundaries and information leakage."""

import unittest

from artwork import COLORS, DETAILED, MINIMAL, REVIEW, inspect_svg, svg_document
from prepare import DATA, INPUTS, SOURCE, check_split, clean_source, fit_idf, read_json, vector


class AnnotationTests(unittest.TestCase):
    def test_annotation_boundaries(self):
        base = [(120, 300, 32), (245, 300, 27), (370, 300, 30)]
        cases = [
            (base, (3, MINIMAL)),
            (base + [(500, 300, 15)], (3, MINIMAL)),
            (base + [(500, 300, 16)], (4, DETAILED)),
            (base + [(710, 300, 16)], (None, REVIEW)),
            (base + [(385, 305, 16)], (None, REVIEW)),
            ([(120, 300, 15)], (0, REVIEW)),
        ]
        for circles, expected in cases:
            with self.subTest(circles=circles):
                self.assertEqual(inspect_svg(svg_document(circles, COLORS[0], "#fff"))[:2], expected)


class DatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.clean = read_json(DATA / "clean.json")
        cls.queries = read_json(DATA / "queries.json")

    def test_idf_and_train_features_ignore_holdout(self):
        original_idf = fit_idf(self.clean)
        mutated = [
            dict(row, description="секретныйтокен " * 20)
            if row["split"] != "train" else row
            for row in self.clean
        ]
        self.assertNotIn("секретныйтокен", original_idf["weights"])
        self.assertEqual(original_idf, fit_idf(mutated))
        self.assertEqual(original_idf, read_json(DATA / "idf.json"))
        train = [row for row in self.clean if row["split"] == "train"]
        self.assertEqual(original_idf["train_ids"], [row["id"] for row in train])
        self.assertEqual(vector("секретныйтокен", original_idf), {})
        self.assertEqual(
            [vector(row["description"], original_idf) for row in train],
            [vector(row["description"], fit_idf(mutated)) for row in train],
        )

    def test_groups_and_queries_do_not_overlap(self):
        _, overlaps = check_split(self.clean, self.queries)
        self.assertEqual(len(overlaps), 3)
        train, test = (
            next(row for row in self.clean if row["split"] == split)
            for split in ("train", "test")
        )
        for field in ("author", "series", "family", "geometry_sha256", "description"):
            with self.subTest(field=field):
                corrupted = [
                    dict(row, **{field: train[field]}) if row["id"] == test["id"] else row
                    for row in self.clean
                ]
                with self.assertRaisesRegex(ValueError, "Пересечение"):
                    check_split(corrupted, self.queries)

        train_query = next(row for row in self.queries if row["split"] == "train")
        test_query = next(row for row in self.queries if row["split"] == "test")
        corrupted = [
            dict(row, text=train_query["text"]) if row["id"] == test_query["id"] else row
            for row in self.queries
        ]
        with self.assertRaisesRegex(ValueError, "Пересечение"):
            check_split(self.clean, corrupted)

    def test_source_cleaning_and_frozen_versions(self):
        source = read_json(SOURCE / "raw.json")
        cleaned, exclusions = clean_source(source[::-1])
        self.assertEqual([row["id"] for row in cleaned], [row["id"] for row in self.clean])
        self.assertEqual({row["id"]: row["reason"] for row in exclusions}, {
            "D001": "duplicate_image", "D002": "duplicate_image", "D003": "duplicate_image",
            "X001": "unknown_rights", "X002": "unknown_rights", "X003": "empty_description",
        })
        policy = read_json(INPUTS / "split_policy.json")
        manifest = read_json(DATA / "manifest.json")
        for field in ("dataset_version", "instruction_version"):
            self.assertEqual(policy[field], manifest[field])


if __name__ == "__main__":
    unittest.main()
