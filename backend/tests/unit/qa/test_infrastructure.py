"""QA-001: тестовая инфраструктура — маркеры, трассировка, фабрики, БД, процессы API.

SPEC 13.1 (pytest, pytest-asyncio, Hypothesis), 17.2а (трассировка), NFR-MNT-01.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import httpx
import pytest
from sqlalchemy import text

from tests.factories import PERSONAS, Sequence, make_user, persona, portal_dilerov, stable_uuid
from tests.plugins.database import ENV_VAR, database_name, isolated_session
from tests.plugins.processes import StartApi

ROOT = Path(__file__).resolve().parents[4]
pytestmark = pytest.mark.spec("17.2а")


def _load_tool():
    spec = importlib.util.spec_from_file_location(
        "traceability", ROOT / "tools" / "traceability.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["traceability"] = module
    spec.loader.exec_module(module)
    return module


traceability = _load_tool()


# --- маркеры и выгрузка ----------------------------------------------------------------------

EXAMPLE_TEST = """
import pytest

pytestmark = pytest.mark.spec("6.5")

@pytest.mark.tc("TC-CALC-01")
@pytest.mark.spec("BR-CALC-03")
def test_example():
    pass

@pytest.mark.gherkin("G-07")
def test_multiplier():
    pass

def test_plain():
    pass
"""


def _ini(pytester: pytest.Pytester) -> None:
    pytester.makeini(
        "[pytest]\nmarkers =\n    tc(id): t\n    spec(id): s\n    gherkin(id): g\n"
        "asyncio_default_fixture_loop_scope = function\n"
        "addopts = --strict-markers -p tests.plugins.traceability -p no:cacheprovider\n"
    )


def test_markers_reach_traceability_dump(pytester: pytest.Pytester) -> None:
    _ini(pytester)
    pytester.makepyfile(test_example=EXAMPLE_TEST)
    out = pytester.path / "trace.json"
    result = pytester.runpytest("--collect-only", "-q", f"--traceability-json={out}")
    result.assert_outcomes()
    dump = json.loads(out.read_text(encoding="utf-8"))
    tests = {t["nodeid"].split("::")[-1]: t for t in dump["tests"]}
    assert tests["test_example"] == {
        "nodeid": "test_example.py::test_example",
        "tc": ["TC-CALC-01"],
        "spec": ["BR-CALC-03", "6.5"],
        "gherkin": [],
        "pending": False,
    }
    assert tests["test_multiplier"]["gherkin"] == ["G-07"]
    assert tests["test_plain"]["tc"] == []


def test_malformed_marker_fails_collection(pytester: pytest.Pytester) -> None:
    _ini(pytester)
    pytester.makepyfile(
        test_bad='import pytest\n\n@pytest.mark.tc("TC-calc-1")\ndef test_bad():\n    pass\n'
    )
    result = pytester.runpytest("--collect-only", "-q")
    assert result.ret != 0
    result.stderr.fnmatch_lines(["*не похож на ID SPEC*"])


def test_example_test_appears_in_report() -> None:
    """Критерий QA-001: тест с маркером попадает в отчёт трассировки."""
    spec = traceability.parse_spec((ROOT / "docs/spec/SPEC.md").read_text(encoding="utf-8"))
    dump = {
        "source": "backend",
        "tests": [
            {"nodeid": "t.py::test_example", "tc": ["TC-CALC-01"], "spec": ["BR-CALC-03"],
             "gherkin": ["G-07"]},
            {"nodeid": "t.py::test_typo", "tc": [], "spec": ["FR-NOPE-99"], "gherkin": []},
        ],
    }  # fmt: skip
    report = traceability.build_report([dump], spec)
    assert "| TC-CALC-01 |" in report.markdown
    assert "`backend: t.py::test_example`" in report.markdown
    assert "| G-07 | Множитель → Повторяющийся лист |" in report.markdown
    assert ("spec", "FR-NOPE-99", "backend: t.py::test_typo") in report.unknown
    assert "Тест-кейсы SPEC 17.1: 1 из" in report.markdown


def test_spec_index_reads_17_1_and_17_2() -> None:
    spec = traceability.parse_spec((ROOT / "docs/spec/SPEC.md").read_text(encoding="utf-8"))
    assert len(spec.gherkin) == 26
    assert spec.gherkin["G-01"] == "Сброс «готово» при правке → Правка оценки в готовой ветке"
    assert spec.gherkin["G-26"].endswith("Пользователь удалён из группы доступа")
    assert {"TC-CALC-01", "TC-SEC-01", "TC-SNAP-01"} <= spec.tc.keys()
    assert spec.knows("spec", "15.2")
    assert spec.knows("spec", "FR-LOCK-01..05")
    assert not spec.knows("spec", "99.1")


def test_tool_writes_report_from_dump(tmp_path: Path) -> None:
    dump = tmp_path / "e2e.json"
    dump.write_text(
        json.dumps({"source": "e2e", "tests": [
            {"nodeid": "x.spec.ts", "tc": [], "spec": ["FR-NOPE-99"], "gherkin": []},
        ]}),
        encoding="utf-8",
    )  # fmt: skip
    out = tmp_path / "report.md"
    assert traceability.main(["--json", str(dump), "--output", str(out)]) == 0
    assert traceability.main(["--json", str(dump), "--output", str(out), "--strict"]) == 1
    assert "## ID, которых нет в SPEC" in out.read_text(encoding="utf-8")


@pytest.mark.spec("17.2а")
def test_require_all_fails_on_missing_or_pending(tmp_path: Path) -> None:
    """QA-027: ворота CI — у каждого TC 17.1 и сценария 17.2 есть тест, шаги не pending."""
    spec = traceability.parse_spec((ROOT / "docs/spec/SPEC.md").read_text(encoding="utf-8"))
    full = [{"nodeid": f"t.py::test_{i}", "tc": [i], "spec": [], "gherkin": []} for i in spec.tc]
    full += [{"nodeid": f"t.py::test_{g}", "tc": [], "spec": [], "gherkin": [g]}
             for g in spec.gherkin]  # fmt: skip
    assert traceability.build_report([{"source": "b", "tests": full}], spec).missing == []
    full[-1]["pending"] = True
    gone = full[1:]
    report = traceability.build_report([{"source": "b", "tests": gone}], spec)
    assert report.missing == [next(iter(spec.tc)), "G-26"]
    dump = tmp_path / "b.json"
    dump.write_text(json.dumps({"source": "b", "tests": gone}), encoding="utf-8")
    out = tmp_path / "r.md"
    assert traceability.main(["--json", str(dump), "--output", str(out)]) == 0
    assert traceability.main(["--json", str(dump), "--output", str(out), "--require-all"]) == 1


# --- фабрики ---------------------------------------------------------------------------------


def test_factories_are_deterministic() -> None:
    seq = Sequence("u{}")
    assert [next(seq), next(seq)] == ["u1", "u2"]
    assert stable_uuid("user", "i.ivanov") == PERSONAS["i.ivanov"].id
    user = make_user(roles=frozenset({"presale"}))
    assert user.login.startswith("user")
    assert user.id == stable_uuid("user", user.login)
    with pytest.raises(ValueError, match="неизвестные"):
        make_user(roles=frozenset({"god"}))
    assert persona("n.novikov").status == "blocked"
    assert persona("i.ivanov", status="blocked").status == "blocked"
    assert PERSONAS["i.ivanov"].status == "active"


def test_portal_dilerov_matches_spec_5_1() -> None:
    project = portal_dilerov()
    leaves = {leaf["title"]: leaf for leaf in project.leaves}
    assert len(leaves) == 9
    assert (leaves["Авторизация"]["o"], leaves["Авторизация"]["r"]) == ("8", "12")
    assert leaves["Создать типовой экран"]["multiplier"] == 12
    assert project.experts_of("d-backend") == ["i.ivanov"]
    assert project.team["a.smirnova"] == ("moderator", None)
    assert project.node_uuid("n-auth") != project.node_uuid("n-profile")
    assert set(project.team) <= set(PERSONAS)


# --- БД --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("worker", "name"), [("gw0", "estimator_test_gw0"), ("main", "estimator_test_main")]
)
def test_database_name_per_worker(worker: str, name: str) -> None:
    assert database_name(worker) == name


def test_database_name_rejects_injection() -> None:
    with pytest.raises(ValueError, match="недопустимое"):
        database_name('x"; DROP DATABASE postgres; --')


@pytest.mark.integration
@pytest.mark.skipif(not os.environ.get(ENV_VAR), reason=f"{ENV_VAR} не задан")
async def test_each_session_is_rolled_back(db_engine) -> None:
    """Записанное в одном тесте (даже после commit) не видно следующему."""
    async with db_engine.connect() as conn:
        await conn.execute(text("CREATE TABLE IF NOT EXISTS qa_probe (v int)"))
        await conn.commit()
    async with isolated_session(db_engine) as session:
        await session.execute(text("INSERT INTO qa_probe VALUES (1)"))
        await session.commit()  # фиксирует только SAVEPOINT
        assert (await session.execute(text("SELECT count(*) FROM qa_probe"))).scalar() == 1
    async with isolated_session(db_engine) as session:
        assert (await session.execute(text("SELECT count(*) FROM qa_probe"))).scalar() == 0


@pytest.mark.integration
@pytest.mark.skipif(not os.environ.get(ENV_VAR), reason=f"{ENV_VAR} не задан")
async def test_db_session_fixture(db_session) -> None:
    assert (
        (await db_session.execute(text("SELECT current_database()")))
        .scalar()
        .startswith("estimator_test_")
    )


# --- два процесса API и клиенты WS -------------------------------------------------------------


async def test_two_processes_and_ws_clients(api_processes: StartApi, ws_connect) -> None:
    first, second = api_processes(2, "tests.support.ws_echo_app:app", factory=False)
    async with httpx.AsyncClient() as client:
        pids = {
            (await client.get(f"{a.base_url}/health/live")).json()["pid"] for a in (first, second)
        }
    assert len(pids) == 2
    replies = set()
    for api in (first, second):
        conn = await ws_connect(f"{api.ws_base_url}/ws")
        await conn.send("ping")
        replies.add(await conn.recv())
    assert replies == {f"{pid}:ping" for pid in pids}


def test_application_process_starts(two_api_processes) -> None:
    for api in two_api_processes:
        assert httpx.get(f"{api.base_url}/health/live").json() == {"status": "ok"}
