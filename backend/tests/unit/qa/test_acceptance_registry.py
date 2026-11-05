"""QA-002: реестр приёмочных сценариев G-01…G-26 совпадает со SPEC 17.2 дословно."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
FEATURES = ROOT / "backend" / "tests" / "acceptance" / "features"
pytestmark = pytest.mark.spec("17.2")


def _spec_blocks() -> list[list[str]]:
    text = (ROOT / "docs" / "spec" / "SPEC.md").read_text(encoding="utf-8")
    part = text[text.index("### 17.2.") : text.index("### 17.2а.")]
    return [
        [line for line in block.splitlines() if line.strip()]
        for block in re.findall(r"```gherkin\n(.*?)```", part, flags=re.DOTALL)
    ]


def _feature_files() -> list[Path]:
    return sorted(FEATURES.glob("*.feature"))


def _body(path: Path) -> list[str]:
    """Строки сценариев без тегов, комментариев и пустых строк."""
    return [
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith(("#", "@"))
    ]


def test_one_feature_file_per_spec_block_verbatim() -> None:
    blocks = _spec_blocks()
    files = _feature_files()
    assert len(blocks) == 15
    assert [_body(f) for f in files] == blocks


def test_every_file_declares_russian() -> None:
    for path in _feature_files():
        assert path.read_text(encoding="utf-8").startswith("# language: ru\n"), path.name


def test_g_ids_follow_spec_order() -> None:
    ids: list[str] = []
    for path in _feature_files():
        lines = path.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines):
            if line.strip().startswith("Сценарий:"):
                tags = lines[i - 1].split()
                g = [t for t in tags if re.fullmatch(r"@G-\d{2}", t)]
                assert len(g) == 1, f"{path.name}: у сценария «{line.strip()}» нет тега @G-NN"
                assert "@api" in tags or "@ui" in tags
                ids.append(g[0][1:])
    assert ids == [f"G-{n:02d}" for n in range(1, 27)]
