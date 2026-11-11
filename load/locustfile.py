"""QA-019 · нагрузочный тест (SPEC NFR-PERF-01, NFR-PERF-03, NFR-PERF-04).

Каждый пользователь Locust — эксперт из слота ``load/seed.py``: открывает дерево своего проекта,
держит WebSocket с подпиской на проект и правит O/R/P своих листьев, между правками догружает
изменения и иногда открывает статистику. Замеры:

* ``PATCH /nodes/{id}`` — подтверждение правки сервером, порог p95 ≤ 300 мс (NFR-PERF-03);
* ``WS node.updated`` — доставка правки другому участнику проекта: от отправки PATCH автором до
  получения события ``node.updated`` каждым из остальных подписчиков (отметки времени ставит один
  процесс Locust, поэтому часы общие), порог p95 ≤ 1 с (NFR-PERF-04).

Запуск (один процесс Locust: отметки отправки хранятся в его памяти, ``--processes`` не нужен):

    LOAD_SLOTS=load/slots.json locust -f load/locustfile.py --headless \\
        --host https://<стенд> -u 50 -r 5 -t 10m --html load-report.html --csv load

Переменные:
    LOAD_SLOTS          JSON из load/seed.py (обязательно)
    LOAD_CA             сертификат УЦ стенда для TLS (иначе — хранилище ОС)
    LOAD_HOSTS          несколько адресов через запятую: пользователи раздаются по кругу (прямо на
                        экземпляры API без Nginx; Origin для WebSocket — из LOAD_ORIGIN)
    LOAD_ORIGIN         Origin для WebSocket (по умолчанию — адрес из --host)
    LOAD_WAIT           пауза между действиями, «мин,макс» в секундах (по умолчанию 3,8)
    LOAD_PATCH_P95_MS   порог p95 PATCH (300)
    LOAD_DELIVERY_P95_MS порог p95 доставки (1000)
    LOAD_MAX_FAIL_RATIO допустимая доля ошибок запросов (0.01)
    LOAD_WARMUP         разогрев в секундах (60): все открывают дерево и подключаются; после него
                        статистика сбрасывается, пороги проверяются по установившемуся режиму

Код выхода 1, если порог не выполнен; итог печатается в конце прогона.
"""

from __future__ import annotations

import contextlib
import itertools
import json
import os
import random
import ssl
import threading
import time
from typing import Any

import gevent
import websocket
from locust import HttpUser, between, events, task
from locust.exception import StopUser

PATCH_NAME = "/nodes/{id}"
DELIVERY_NAME = "node.updated (доставка другому участнику)"
SENT_TTL = 30.0  # с: отметки отправки старше этого удаляются из памяти


def _env_float(name: str, default: float) -> float:
    return float(os.environ.get(name, default))


def _load_slots() -> list[dict[str, Any]]:
    path = os.environ.get("LOAD_SLOTS")
    if not path:
        raise SystemExit("LOAD_SLOTS: укажите JSON со слотами из load/seed.py")
    with open(path, encoding="utf-8") as fh:
        return list(json.load(fh)["slots"])


SLOTS = _load_slots()
_slot_counter = itertools.count()
_slot_lock = threading.Lock()
_hosts = [h.strip().rstrip("/") for h in os.environ.get("LOAD_HOSTS", "").split(",") if h.strip()]
_wait = [float(x) for x in os.environ.get("LOAD_WAIT", "3,8").split(",")]

# (node_id, version) → время отправки PATCH; общий для всех пользователей процесса
_sent: dict[tuple[str, int], float] = {}
_delivered = 0
# Время PATCH по размеру проекта (для отчёта): «большой» — от 1 000 узлов
_patch_by_size: dict[str, list[float]] = {"большой проект": [], "малые проекты": []}


def _next_slot() -> int:
    with _slot_lock:
        return next(_slot_counter)


def _remember(node_id: str, version: int, started: float) -> None:
    _sent.setdefault((node_id, version), started)


def _sweep(now: float) -> None:
    for key, started in list(_sent.items()):
        if now - started > SENT_TTL:
            _sent.pop(key, None)


class Expert(HttpUser):
    wait_time = between(_wait[0], _wait[-1])
    host = _hosts[0] if _hosts else None

    def on_start(self) -> None:
        index = _next_slot()
        if index >= len(SLOTS):
            raise StopUser(f"слотов {len(SLOTS)}: увеличьте их в load/seed.py")
        self.slot = SLOTS[index]
        if _hosts:
            self.client.base_url = _hosts[index % len(_hosts)]
        ca = os.environ.get("LOAD_CA")
        if ca:
            self.client.verify = ca
        self.project_id = self.slot["project_id"]
        self.user_id = self.slot["user_id"]
        self.cookie = f"__Host-session={self.slot['session']}"
        self.client.headers.update(
            {"Cookie": self.cookie, "X-CSRF-Token": self.slot["csrf"], "Accept": "application/json"}
        )
        self.versions: dict[str, int] = {}
        self.project_version = 0
        self._load_tree()
        self._ws_alive = True
        self._ws: websocket.WebSocket | None = None
        self._ws_job = gevent.spawn(self._listen)

    def on_stop(self) -> None:
        self._ws_alive = False
        if self._ws is not None:
            with contextlib.suppress(Exception):  # соединение уже закрыто
                self._ws.close()
        self._ws_job.kill(block=False)

    # --- REST ---

    def _load_tree(self) -> None:
        with self.client.get(
            f"/api/v1/projects/{self.project_id}/tree",
            name="/projects/{id}/tree",
            catch_response=True,
        ) as resp:
            if resp.status_code != 200:
                resp.failure(f"дерево: {resp.status_code} {resp.text[:200]}")
                raise StopUser
            data = resp.json()
        mine = set(self.slot["leaves"])
        self.versions = {n["id"]: n["version"] for n in data["nodes"] if n["id"] in mine}
        self.size = "большой проект" if len(data["nodes"]) >= 1000 else "малые проекты"
        self.project_version = int(data.get("project_version") or 0)
        if not self.versions:
            raise StopUser("в дереве нет листьев слота")

    @task(10)
    def edit_estimate(self) -> None:
        node_id = random.choice(list(self.versions))  # noqa: S311 — не криптография
        base = self.versions[node_id]
        x = random.randint(1, 40)  # noqa: S311
        body = {"base_version": base, "changes": {"o": str(x), "r": str(x + 2), "p": str(x + 5)}}
        started = time.time()
        # Событие может прийти раньше ответа. Перезапись: отметка неудачной попытки с той же
        # версией не должна остаться временем отправки этой правки
        _sent[(node_id, base + 1)] = started
        with self.client.patch(
            f"/api/v1/nodes/{node_id}", json=body, name=PATCH_NAME, catch_response=True
        ) as resp:
            if resp.status_code == 200:
                _patch_by_size[self.size].append((time.time() - started) * 1000)
                data = resp.json()
                version = int(data["node"]["version"])
                self.versions[node_id] = version
                _remember(node_id, version, started)
                self.project_version = max(self.project_version, int(data["project_version"]))
            elif resp.status_code == 409:
                resp.failure(f"409 {resp.text[:200]}")
                self._load_tree()  # чужая правка своего листа быть не должна: перечитать
            else:
                resp.failure(f"{resp.status_code} {resp.text[:200]}")

    @task(3)
    def catch_up(self) -> None:
        with self.client.get(
            f"/api/v1/projects/{self.project_id}/changes",
            params={"since": self.project_version},
            name="/projects/{id}/changes",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                version = resp.json().get("to_version")
                if version is not None:
                    self.project_version = max(self.project_version, int(version))
            elif resp.status_code == 410:
                resp.success()
                self._load_tree()
            else:
                resp.failure(f"{resp.status_code} {resp.text[:200]}")

    @task(1)
    def open_stats(self) -> None:
        self.client.get(f"/api/v1/projects/{self.project_id}/stats", name="/projects/{id}/stats")

    # --- WebSocket ---

    def _ws_url(self) -> str:
        base = self.client.base_url or self.host or ""
        scheme, rest = base.split("://", 1)
        return f"{'wss' if scheme == 'https' else 'ws'}://{rest}/api/v1/ws"

    def _listen(self) -> None:
        origin = os.environ.get("LOAD_ORIGIN") or (self.host or self.client.base_url)
        ca = os.environ.get("LOAD_CA")
        sslopt = {"ca_certs": ca} if ca else {"cert_reqs": ssl.CERT_REQUIRED}
        while self._ws_alive:
            started = time.time()
            try:
                self._ws = websocket.create_connection(
                    self._ws_url(),
                    header=[f"Cookie: {self.cookie}"],
                    origin=origin,
                    sslopt=sslopt,
                    timeout=30,
                )
                self._ws.send(
                    json.dumps(
                        {
                            "op": "subscribe",
                            "req_id": "load",
                            "project_id": self.project_id,
                            "since": self.project_version,
                        }
                    )
                )
                events.request.fire(
                    request_type="WS",
                    name="connect + subscribe",
                    response_time=(time.time() - started) * 1000,
                    response_length=0,
                    exception=None,
                    context={},
                )
                while self._ws_alive:
                    try:
                        raw = self._ws.recv()
                    except websocket.WebSocketTimeoutException:
                        continue
                    if raw:
                        self._on_message(raw)
            except Exception as exc:  # noqa: BLE001 — соединение упало: отметить и переподключиться
                if not self._ws_alive:
                    return
                events.request.fire(
                    request_type="WS",
                    name="connect + subscribe",
                    response_time=(time.time() - started) * 1000,
                    response_length=0,
                    exception=exc,
                    context={},
                )
                gevent.sleep(1)

    def _on_message(self, raw: str | bytes) -> None:
        global _delivered
        received = time.time()
        msg = json.loads(raw)
        if msg.get("type") == "error":
            events.request.fire(
                request_type="WS",
                name=f"error {msg.get('op')}",
                response_time=0,
                response_length=len(raw),
                exception=RuntimeError(msg.get("code")),
                context={},
            )
            return
        if msg.get("type") != "event" or msg.get("event") != "node.updated":
            return
        data = msg["data"]
        if data["author"]["id"] == self.user_id:
            return
        node = data["node"]
        started = _sent.get((node["id"], int(node["version"])))
        if started is None:
            return  # правка не из этого прогона (или отметка уже устарела)
        _delivered += 1
        events.request.fire(
            request_type="WS",
            name=DELIVERY_NAME,
            response_time=(received - started) * 1000,
            response_length=len(raw),
            exception=None,
            context={},
        )
        if _delivered % 500 == 0:
            _sweep(received)


@events.test_start.add_listener
def _schedule_warmup_reset(environment: Any, **_kw: Any) -> None:
    warmup = _env_float("LOAD_WARMUP", 60)
    if warmup <= 0:
        return

    def reset() -> None:
        gevent.sleep(warmup)
        environment.stats.reset_all()
        for samples in _patch_by_size.values():
            samples.clear()
        print(f"QA-019: разогрев {warmup:.0f} с окончен, статистика сброшена")

    gevent.spawn(reset)


@events.quitting.add_listener
def _check_thresholds(environment: Any, **_kw: Any) -> None:
    stats = environment.stats
    patch = stats.get(PATCH_NAME, "PATCH")
    delivery = stats.get(DELIVERY_NAME, "WS")
    patch_limit = _env_float("LOAD_PATCH_P95_MS", 300)
    delivery_limit = _env_float("LOAD_DELIVERY_P95_MS", 1000)
    fail_limit = _env_float("LOAD_MAX_FAIL_RATIO", 0.01)
    total = stats.total
    fail_ratio = total.num_failures / total.num_requests if total.num_requests else 1.0
    problems = []
    if not patch.num_requests:
        problems.append("ни одного PATCH")
    elif (p95 := patch.get_response_time_percentile(0.95)) > patch_limit:
        problems.append(f"PATCH p95 {p95:.0f} мс > {patch_limit:.0f}")
    if not delivery.num_requests:
        problems.append("ни одной доставки node.updated")
    elif (d95 := delivery.get_response_time_percentile(0.95)) > delivery_limit:
        problems.append(f"доставка p95 {d95:.0f} мс > {delivery_limit:.0f}")
    if fail_ratio > fail_limit:
        problems.append(f"ошибок {fail_ratio:.2%} > {fail_limit:.2%}")
    patch95 = patch.get_response_time_percentile(0.95) or 0
    delivery95 = delivery.get_response_time_percentile(0.95) or 0
    print(
        f"QA-019 итог: PATCH {patch.num_requests} шт., p95 {patch95:.0f} мс; "
        f"доставок {delivery.num_requests}, p95 {delivery95:.0f} мс; "
        f"ошибок {total.num_failures} из {total.num_requests}"
    )
    for size, samples in _patch_by_size.items():
        if samples:
            ordered = sorted(samples)
            p95_size = ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]
            p50_size = ordered[len(ordered) // 2]
            print(
                f"QA-019 PATCH, {size}: {len(ordered)} шт., "
                f"p50 {p50_size:.0f} мс, p95 {p95_size:.0f} мс"
            )
    if problems:
        print("QA-019: порог не выполнен — " + "; ".join(problems))
        environment.process_exit_code = 1
    else:
        print("QA-019: пороги NFR-PERF-01/03/04 выполнены")
