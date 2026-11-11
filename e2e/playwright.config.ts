/**
 * FE-090 · Playwright. По умолчанию сценарии идут против локальной связки: API на :8000 и
 * serve.mjs (HTTPS, статика frontend/dist, CSP-nonce как у Nginx). На dev-стенде:
 * E2E_BASE_URL=https://localhost:8443 и E2E_SEED_CMD с командой seed.py внутри контейнера api.
 *
 * Замеры производительности (`perf/`, FE-081) идут отдельно: `E2E_PERF=1 npx playwright test perf`. Входы всех сценариев
 * укладываются в лимит FR-LOCK-02 (20 попыток в минуту с IP) через `auth/budget.ts`.
 * Они долгие, и их вход добавлял бы к общему прогону ещё одну попытку при лимите входов с одного IP.
 */
import { defineConfig, devices } from '@playwright/test';

const PERF = Boolean(process.env.E2E_PERF);

const external = process.env.E2E_BASE_URL;
const baseURL = external ?? 'https://localhost:8443';

export default defineConfig({
  testDir: '.',
  testMatch: '**/*.spec.ts',
  // FE-094: e2e/ad очищает базу (установка с нуля) и нужен Samba AD — только при E2E_AD=1 (на
  // домашнем стенде его задаёт seed-env) и последним, после всех остальных наборов
  projects: [
    { name: 'main', testIgnore: PERF ? ['ad/**'] : ['perf/**', 'ad/**'] },
    ...(process.env.E2E_AD === '1' ? [{ name: 'ad', testMatch: 'ad/**/*.spec.ts', dependencies: ['main'] }] : []),
  ],
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 60_000,
  reporter: [['list']],
  globalSetup: './global-setup.ts',
  use: {
    baseURL,
    locale: 'ru-RU',
    timezoneId: 'Europe/Moscow',
    ignoreHTTPSErrors: true,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    ...devices['Desktop Chrome'],
    // Chromium берёт кодировку имён файлов из локали процесса: без UTF-8 (LANG пуст в контейнерах)
    // кириллическое имя выгрузки («Проект_дата_вопросы.docx») он заменяет на «download».
    launchOptions: { env: { ...process.env, LANG: 'C.UTF-8', LC_ALL: 'C.UTF-8' } },
  },
  webServer: external
    ? undefined
    : { command: 'node serve.mjs', url: `${baseURL}/login`, ignoreHTTPSErrors: true, reuseExistingServer: true },
});
