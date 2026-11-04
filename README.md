# Приложение оценки проектов

Спецификация лежит в [docs/spec/SPEC.md](docs/spec/SPEC.md) (версия 0.5 от 04.11.2026).

- `docs/spec/img/` — картинки макетов экранов, `docs/spec/mockups-src/` — их HTML-исходники.
- `docs/spec/review/` — ревью, журналы решений и прошлые версии спецификации.
- HTML-версия собирается так: `pip install markdown && python3 docs/spec/build.py docs/spec/SPEC.md spec.html docs/spec/tpl.html`.

Как устроена работа:

- [PLAN.md](PLAN.md) — план реализации: этапы, треки, задачи, владение файлами.
- [DESIGN.md](DESIGN.md) — правила дизайна интерфейса.
- [AGENTS.md](AGENTS.md) — обязательный регламент работы агентов и субагентов: роли и полномочия, разрешение коллизий, работа с репозиторием, информационная безопасность, эскалация, журналирование. Журнал решений и инцидентов — [agents/journal/](agents/journal/).
