"""Project metadata consistency checks."""

from pathlib import Path


def test_readme_license_badge_matches_mpl() -> None:
    """README badge should match the repository's MPL-2.0 license."""
    repo_root = Path(__file__).resolve().parents[1]
    readme_text = (repo_root / "README.md").read_text(encoding="utf-8")
    license_text = (repo_root / "LICENSE").read_text(encoding="utf-8")

    assert "license-MPL--2.0" in readme_text
    assert "Mozilla Public License Version 2.0" in license_text
