from __future__ import annotations

import tomllib
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class DeploymentContractTests(unittest.TestCase):
    def test_cloud_entrypoint_and_single_dependency_file_are_present(self) -> None:
        self.assertTrue((PROJECT_ROOT / "app.py").is_file())
        self.assertFalse((PROJECT_ROOT / "streamlit_app.py").exists())
        self.assertTrue((PROJECT_ROOT / "requirements.txt").is_file())
        self.assertFalse((PROJECT_ROOT / "environment.yml").exists())
        self.assertTrue((PROJECT_ROOT / "environment.local.yml").is_file())

    def test_requirements_installs_project_ui_extra(self) -> None:
        requirements = (PROJECT_ROOT / "requirements.txt").read_text(encoding="utf-8")

        self.assertEqual(requirements.strip(), "-e .[ui]")

    def test_streamlit_and_upload_limit_are_pinned(self) -> None:
        pyproject = tomllib.loads(
            (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        )
        config = tomllib.loads(
            (PROJECT_ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8")
        )

        self.assertEqual(
            pyproject["project"]["optional-dependencies"]["ui"],
            ["streamlit==1.63.0"],
        )
        self.assertEqual(config["server"]["maxUploadSize"], 50)


if __name__ == "__main__":
    unittest.main()
