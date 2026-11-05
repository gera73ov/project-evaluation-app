# Приложение оценки проектов

Спецификация лежит в [docs/spec/SPEC.md](docs/spec/SPEC.md) (версия 0.5 от 04.11.2026).

- `docs/spec/img/` — картинки макетов экранов, `docs/spec/mockups-src/` — их HTML-исходники.
- `docs/spec/review/` — ревью, журналы решений и прошлые версии спецификации.
- HTML-версия собирается так: `pip install markdown && python3 docs/spec/build.py docs/spec/SPEC.md spec.html docs/spec/tpl.html`.

Как устроена работа:

- [PLAN.md](PLAN.md) — план реализации: этапы, треки, задачи, владение файлами.
- [DESIGN.md](DESIGN.md) — правила дизайна интерфейса.
- [AGENTS.md](AGENTS.md) — обязательный регламент работы агентов и субагентов: роли и полномочия, разрешение коллизий, работа с репозиторием, информационная безопасность, эскалация, журналирование. Журнал решений и инцидентов — [agents/journal/](agents/journal/).

## Разработка

Нужны Docker 24+ с compose, [uv](https://docs.astral.sh/uv/), Node.js 22 и Python 3. В Windows команды запускаются из WSL2.

- `make up` — поднять dev-стенд (nginx, api ×2, worker, beat, PostgreSQL 16, Redis 7, ClamAV) и дождаться healthcheck. Приложение: https://localhost:8443. Сертификаты выпускает свой dev-УЦ, его файл `deploy/compose/certs/ca.crt` нужно добавить в доверенные браузера.
- `make up-test` — то же плюс эмуляторы корпоративных сервисов: Samba AD DC (LDAPS на 127.0.0.1:1636), Mailpit (письма на http://127.0.0.1:8025), syslog-приёмник TLS вместо SIEM (127.0.0.1:6514). `make smoke-test` проверяет их по протоколам.
- `make check` — все проверки CI локально: линтеры, тесты с порогами покрытия, bandit, semgrep, pip-audit, npm audit.
- `make help` — список всех команд, `make down` — остановить стенд.

Переменные окружения dev-стенда — в [.env.example](.env.example) (`make env` создаёт `.env` со случайными паролями). Полный список переменных приложения с описанием и значениями по умолчанию выводит `uv --directory backend run estimator config-env`.
