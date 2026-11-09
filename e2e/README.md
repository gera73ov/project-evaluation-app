# E2E (FE-090, QA-018)

Playwright-сценарии UI против настоящего API.

## Запуск на dev-стенде

```bash
cd e2e && npm ci
E2E_BASE_URL=https://dev.example.local \
E2E_SEED_CMD='docker compose -f ../deploy/compose/docker-compose.yml exec -T api python /e2e/auth/seed.py' \
npx playwright test
```

## Запуск без Docker

Нужны Postgres и Redis, применённые миграции (`uv run estimator migrate`) и API на `127.0.0.1:8000`
с `APP_BASE_URL=https://localhost:8443`. Затем:

```bash
(cd frontend && npm run build)
cd e2e && npm ci && npx playwright test
```

Без `E2E_BASE_URL` поднимается `serve.mjs` — замена Nginx стенда: HTTPS на 8443, статика
`frontend/dist`, nonce в CSP, прокси `/api`. Самоподписанный сертификат создаётся в `e2e/.tls`.
`global-setup.ts` запускает `auth/seed.py`: тот создаёт пользователя и администратора со случайными
логинами, поэтому повторный прогон не мешает прошлому. Лимит входа с одного IP (20 в минуту) при
частых локальных прогонах сбрасывается очисткой Redis.
