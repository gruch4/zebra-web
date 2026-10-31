from pathlib import Path

import pytest

from app.render.renderer import render_zpl

PRINT_TESTS = Path(__file__).resolve().parents[2] / "docs" / "print-tests"


@pytest.mark.parametrize("path", sorted(PRINT_TESTS.glob("*.zpl")), ids=lambda path: path.stem)
def test_print_test_labels_render(path: Path):
    """The physical test labels (docs/print-tests) render, so their preview can be compared."""
    result = render_zpl(path.read_text(encoding="utf-8"), dpi=300 if "300dpi" in path.stem else 203)
    assert result.label_count >= 1
    assert not any("Unsupported" in w or "Invalid" in w for w in result.warnings), result.warnings


def test_all_print_tests_are_present():
    assert len(list(PRINT_TESTS.glob("T*.zpl"))) == 18
