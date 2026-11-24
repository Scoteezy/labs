"""Check catalog admission and image integrity with real Lab 11 resources."""

import json
import unittest
from pathlib import Path
from shutil import copyfile
from tempfile import TemporaryDirectory
from unittest.mock import patch

from lab07.baseline import sha256
from lab11 import search


class SearchResourceTests(unittest.TestCase):
    def test_rejected_cards_are_excluded_in_both_modes_and_from_image_access(self):
        config = search.load_config(search.DEFAULT_CONFIG)
        catalog = search.load_json(config, search.CATALOG)
        manifest = search.load_json(config, search.MANIFEST)
        catalog_by_id = {row["id"]: row for row in catalog}
        catalog_by_id["P011"]["rights_status"] = "unknown"
        catalog_by_id["P027"]["source"] = " "

        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest["files_sha256"]["clean.json"] = self.write_fixture(root, search.CATALOG, catalog)
            config["sha256"][search.CATALOG] = manifest["files_sha256"]["clean.json"]
            config["sha256"][search.MANIFEST] = self.write_fixture(root, search.MANIFEST, manifest)
            for name in (search.SPLIT, search.BASE_IDF, search.LEXICON, search.CANDIDATE_IDF):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                copyfile(search.REPO / name, path)
            config_path = root / "config.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")

            with patch.object(search, "REPO", root):
                for mode in ("baseline", "candidate"):
                    with self.subTest(mode=mode):
                        service = search.SearchService.load(config_path, mode=mode)
                        result = service.search({"query": "афиша крупным акцентом"})
                        self.assertEqual(result["mode"], mode)
                        self.assertEqual(result["status"], "ok")
                        ids = [row["id"] for row in result["results"]]
                        self.assertIn("P001", ids)
                        for rejected in ("P011", "P027"):
                            self.assertNotIn(rejected, ids)
                            with self.assertRaises(search.ApiError) as error:
                                service.get_image(rejected)
                            self.assertEqual((error.exception.status, error.exception.code),
                                             (404, "poster_not_found"))

    def test_image_content_must_match_catalog_fingerprint(self):
        service = search.SearchService.load()
        expected = (search.REPO / "lab06/data/posters/P001.svg").read_bytes()
        self.assertEqual(service.get_image("P001"), expected)

        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "lab06/data/posters/P001.svg"
            path.parent.mkdir(parents=True)
            path.write_bytes(expected + b"\n")
            with patch.object(search, "REPO", root), self.assertRaises(search.ApiError) as error:
                service.get_image("P001")
            self.assertEqual((error.exception.status, error.exception.code), (503, "image_unavailable"))

    @staticmethod
    def write_fixture(root: Path, name: str, value: object) -> str:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(value, ensure_ascii=False).encode("utf-8")
        path.write_bytes(payload)
        return sha256(payload)


if __name__ == "__main__":
    unittest.main()
