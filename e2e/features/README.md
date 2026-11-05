# Сценарии UI (QA-002)

Текст приёмочных сценариев SPEC 17.2 (G-01…G-26) хранится в одном месте —
[backend/tests/acceptance/features/](../../backend/tests/acceptance/features/), чтобы две копии
не расходились со спецификацией. Тест `backend/tests/unit/qa/test_acceptance_registry.py`
сверяет их со SPEC дословно.

Сценарии с тегом `@ui` проверяются ещё и в браузере: G-03, G-07, G-08, G-11, G-13, G-14,
G-15, G-19, G-21. Playwright (задачи FE и QA-018) читает эти же `.feature`-файлы, отбирая их
по тегу `@ui`, а шаги UI кладёт в `e2e/steps/`. Пока шаги не реализованы, у сценариев стоит
тег `@pending`.
