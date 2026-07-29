import json
import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.catalog.technology_catalog import inject_technology_catalog


class TechnologyCatalogInjectorTests(unittest.TestCase):
    def test_injector_preserves_known_keys_and_reads_civilization_folders(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            catalog_path = root / "data" / "technologies.json"
            catalog_path.parent.mkdir()
            catalog_path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "templatesRoot": "templates/tech",
                        "technologies": [
                            {
                                "key": "wood_1",
                                "displayName": "wood_1",
                                "building": "lumber_camp",
                                "templates": ["economy/double_broadaxe.png"],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            sis_template = root / "templates" / "tech" / "economy" / "age2"
            french_template = root / "templates" / "tech" / "french" / "military" / "age3"
            sis_template.mkdir(parents=True)
            french_template.mkdir(parents=True)
            (sis_template / "double_broadaxe.png").touch()
            (french_template / "royal_bloodlines.png").touch()

            inject_technology_catalog(catalog_path, civilization="sis")
            catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
            technologies = {entry["key"]: entry for entry in catalog["technologies"]}

            self.assertEqual(technologies["wood_1"]["civilization"], "sis")
            self.assertEqual(technologies["wood_1"]["ageAvailable"], "feudal")
            self.assertEqual(technologies["wood_1"]["building"], "lumber_camp")
            self.assertEqual(technologies["royal_bloodlines"]["civilization"], "french")
            self.assertEqual(technologies["royal_bloodlines"]["category"], "military")
            self.assertEqual(technologies["royal_bloodlines"]["ageAvailable"], "castle")


if __name__ == "__main__":
    unittest.main()
