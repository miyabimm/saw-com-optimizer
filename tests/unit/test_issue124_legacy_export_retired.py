from pathlib import Path


def test_legacy_exporter_is_absent_and_r5_entrypoints_remain():
    """Check the retirement statically; do not import or execute project code."""
    root = Path(__file__).resolve().parents[2]
    package = root / "src" / "sawopt"

    assert not (package / "__main__.py").exists()
    assert not (package / "reporting" / "github_review.py").exists()
    assert all(
        "github_review" not in path.read_text(encoding="utf-8")
        for path in package.rglob("*.py")
    )

    assert (package / "cli.py").is_file()
    assert (package / "io" / "experiment_store.py").is_file()
    assert (package / "reporting" / "experiment_review.py").is_file()
    assert 'sawopt = "sawopt.cli:main"' in (root / "pyproject.toml").read_text(encoding="utf-8")
