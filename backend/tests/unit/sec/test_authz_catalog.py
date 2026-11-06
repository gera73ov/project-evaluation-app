"""SEC-005: загрузка каталога прав и инварианты R-SUM, R-SUPPORT (contracts/permissions.yaml)."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml

from estimator.security.authz import catalog as cat_mod
from estimator.security.authz.catalog import CatalogError, load_catalog, parse

pytestmark = [pytest.mark.spec("SEC-AUTHZ-02"), pytest.mark.spec("BR-ROLE-01")]

RAW: dict[str, Any] = yaml.safe_load(cat_mod._path().read_text(encoding="utf-8"))


def _raw() -> dict[str, Any]:
    return copy.deepcopy(RAW)


def test_catalog_loads() -> None:
    catalog = load_catalog()
    assert catalog.version == "1.0.0"
    assert len(catalog.permissions) == 84  # 83 по M0 + session.password_change (CR-003)
    assert catalog.permission("money.read").is_money
    assert catalog.permission("export.money").is_money
    assert not catalog.permission("tree.read").is_money
    assert {g.source for g in catalog.grants["reviewer"]} == {"reviewer"}
    assert catalog.required_settings(("project.ad_search",)) == {"auth.mode"}
    assert catalog.required_settings(("tree.read",)) == frozenset()


def test_unknown_permission_raises_key_error() -> None:
    with pytest.raises(KeyError, match="отсутствует"):
        load_catalog().permission("tree.write.any")


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda d: d["grants"]["expert"].append({"permission": "money.read",
                                                  "context": "member"}), "R-SUM"),
        (lambda d: d["grants"]["admin"].append({"permission": "tree.write",
                                                 "context": "support_session"}), "R-SUPPORT"),
        (lambda d: d["grants"]["admin"].append({"permission": "nope"}), "неизвестное право"),
        (lambda d: d["grants"]["admin"].append({"permission": "users.read",
                                                 "context": "space"}), "контекст"),
        (lambda d: d["grants"]["admin"].append({"permission": "users.read",
                                                 "context": "member"}), "member"),
        (lambda d: d["matrix_3_4"][0]["permissions"].append("nope"), "неизвестное право"),
        (lambda d: d["grants"]["admin"].append({"permission": "users.read",
                                                 "requires_setting": "auth.mode"}), "без значения"),
    ],
)  # fmt: skip
def test_invariants_are_enforced(mutate: Any, message: str) -> None:
    data = _raw()
    mutate(data)
    with pytest.raises(CatalogError, match=message):
        parse(data)


def test_path_override_and_packaged_copy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src = cat_mod._path()
    target = tmp_path / "custom.yaml"
    target.write_bytes(src.read_bytes())
    monkeypatch.setenv(cat_mod.ENV_PATH, str(target))
    assert cat_mod._path() == target
    monkeypatch.delenv(cat_mod.ENV_PATH)

    packaged = tmp_path / "authz" / "catalog.py"
    packaged.parent.mkdir()
    (packaged.parent / cat_mod.FILE_NAME).write_bytes(src.read_bytes())
    monkeypatch.setattr(cat_mod, "__file__", str(packaged))
    assert cat_mod._path() == packaged.parent / cat_mod.FILE_NAME


def test_missing_catalog_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cat_mod, "__file__", str(tmp_path / "catalog.py"))
    with pytest.raises(CatalogError, match="не найден"):
        cat_mod._path()


def test_dockerfile_ships_catalog() -> None:
    root = Path(__file__).resolve().parents[4]
    dockerfile = (root / "deploy" / "docker" / "api.Dockerfile").read_text(encoding="utf-8")
    assert "COPY contracts/permissions.yaml ./src/estimator/security/authz/permissions.yaml" in (
        dockerfile
    )
