/**
 * FE-093 · статистика, снимки, сравнение и портфель на настоящем API (SPEC 10.x, 11.8–11.13):
 * модератор заводит проект (две фазы, две дисциплины, узлы — `../perf/fill.py`, эксперт первой
 * дисциплины, статус «Оценка»); итоги на вкладке «Итоги» совпадают с итогами сервера и верхней
 * панели рабочего экрана; «Напомнить не начавшим» уходит эксперту; модератор делает снимок
 * «v1 — КП отправлено», меняет оценку и сравнивает снимок с текущим состоянием; руководитель
 * пресейла находит проект в портфеле и становится модератором. Сценарии идут по порядку.
 *
 * Выгрузки (Excel «С деньгами», вопросы в Word) — после серверной части EXP.
 */
import { readFileSync } from 'node:fs';
import { expect, test, type Browser, type BrowserContext, type Page } from '@playwright/test';

import { STATS_DATA_FILE, runJson } from '../global-setup';
import { currentStep, totp } from '../auth/totp';
import { spendLogin } from '../auth/budget';

interface Person {
  id: string;
  login: string;
  name: string;
}

interface Seed {
  moderator: Person;
  head: Person;
  expert: Person;
  phases: string[];
  disciplines: string[];
  password: string;
  totp: string;
}

interface Figures {
  e: string;
  p80: string;
  p90: string;
}

const seed = JSON.parse(readFileSync(STATS_DATA_FILE, 'utf8')) as Seed;
const FILL = process.env.E2E_STATS_FILL_CMD ?? 'uv run --frozen python ../e2e/perf/fill.py';
const PROJECT = `E2E статистика ${Date.now()}`;
const SNAPSHOT = 'v1 — КП отправлено';
/** Первый лист первой ветки после `fill.py`: O–R–P = 2–4–8. */
const LEAF = 'Задача Модуль 1.1.1';

test.describe.configure({ mode: 'serial' });

let lastStep = 0;
const contexts: BrowserContext[] = [];
const cspErrors: string[] = [];
let moderator: Page;
let projectId = '';

/** Вход с TOTP; все пользователи сценария — с одним секретом, шаг не повторяется. */
async function open(browser: Browser, who: Person): Promise<Page> {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  contexts.push(context);
  const page = await context.newPage();
  page.on('console', (message) => {
    if (message.type() === 'error' && /Content Security Policy/i.test(message.text())) cspErrors.push(message.text());
  });
  await page.goto('/login');
  await page.getByLabel('Логин').fill(who.login);
  await page.getByLabel('Пароль').fill(seed.password);
  await spendLogin();
  await page.getByRole('button', { name: 'Войти' }).click();
  while (currentStep() <= lastStep) await page.waitForTimeout(1000);
  lastStep = currentStep();
  await page.getByLabel('Цифра 1').pressSequentially(totp(seed.totp, lastStep));
  await expect(page).not.toHaveURL(/\/login/);
  return page;
}

async function api<T>(page: Page, method: string, path: string, data?: unknown): Promise<T> {
  const csrf = (await page.context().cookies()).find((c) => c.name === '__Host-csrf')?.value ?? '';
  const response = await page.request.fetch(`/api/v1${path}`, { method, data, headers: { 'X-CSRF-Token': csrf } });
  const text = await response.text();
  expect(response.ok(), `${method} ${path}: ${text}`).toBe(true);
  return (text ? JSON.parse(text) : null) as T;
}

/** Часы, как их пишет экран: одна цифра после запятой, разряды через неразрывный пробел. */
function hours(value: string): string {
  return new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 1, maximumFractionDigits: 1 }).format(Number(value));
}

/** Текст без различий в пробелах: в разрядах числа стоят неразрывные пробелы. */
const plain = (text: string) => text.replace(/\s+/g, ' ');

test.beforeAll(async ({ browser }) => {
  moderator = await open(browser, seed.moderator);
  const { project } = await api<{ project: { id: string } }>(moderator, 'POST', '/projects', {
    name: PROJECT,
    customer: 'ООО «Статистика»',
    phase_ids: seed.phases,
  });
  projectId = project.id;
  for (const id of seed.disciplines) {
    await api(moderator, 'POST', `/projects/${projectId}/disciplines`, { discipline_id: id });
  }
  runJson(`${FILL} ${projectId} 60`);
  // эксперт первой дисциплины — адресат «Напомнить не начавшим»
  await api(moderator, 'PUT', `/projects/${projectId}/members`, {
    members: [
      { user_id: seed.moderator.id, role: 'moderator' },
      { user_id: seed.expert.id, role: 'expert', discipline_id: seed.disciplines[0] },
    ],
  });
  // снимки делают в «Оценке», «Сведении» и «Завершена» (BR-PRJ-02)
  await api(moderator, 'POST', `/projects/${projectId}/status`, { to: 'estimation' });
});

test.afterEach(() => {
  expect(cspErrors).toEqual([]);
});

test.afterAll(async () => {
  for (const context of contexts) await context.close();
});

test('итоги на вкладке «Итоги» совпадают с сервером и верхней панелью рабочего экрана', async () => {
  const { totals } = await api<{ totals: { total: Figures } }>(moderator, 'GET', `/projects/${projectId}/stats`);
  await moderator.goto(`/projects/${projectId}`);
  const top = moderator.getByLabel('Итог часов', { exact: true });
  await expect(top).toBeVisible();
  expect(plain(await top.innerText())).toContain(`E ${plain(hours(totals.total.e))}`);

  await moderator.goto(`/projects/${projectId}/stats/totals`);
  const total = moderator.getByRole('row', { name: /^Итог/ });
  await expect(total).toBeVisible();
  const text = plain(await total.innerText());
  for (const value of [totals.total.e, totals.total.p80, totals.total.p90]) expect(text).toContain(plain(hours(value)));
});

test('«Напомнить не начавшим» на сетке готовности уходит эксперту ветки «не начато»', async () => {
  await moderator.goto(`/projects/${projectId}/stats`);
  const button = moderator.getByRole('button', { name: /Напомнить не начавшим/ });
  await expect(button).toBeEnabled();
  await button.click();
  await expect(moderator.getByText('Напоминание отправлено 1 эксперту')).toBeVisible();
});

test('снимок «v1 — КП отправлено», правка оценки, сравнение с текущим', async () => {
  await moderator.goto(`/projects/${projectId}`);
  await moderator.getByRole('button', { name: /Снимок$/ }).click();
  const dialog = moderator.getByRole('dialog', { name: 'Снимок проекта' });
  await dialog.getByRole('textbox', { name: 'Название' }).fill(SNAPSHOT);
  await dialog.getByRole('button', { name: 'Сделать снимок' }).click();
  await expect(moderator.getByText(`Снимок «${SNAPSHOT}» сохранён`)).toBeVisible();

  const tree = moderator.getByRole('treegrid', { name: 'Дерево оценки' });
  const leaf = tree.locator('.vrow [role="row"]').filter({ hasText: LEAF }).first();
  await leaf.getByRole('button', { name: /^O:/ }).click();
  const input = leaf.getByRole('textbox', { name: 'O' });
  await input.fill('3');
  await input.press('Enter');
  await expect(leaf.getByRole('button', { name: 'O: 3' })).toBeVisible();

  await moderator.goto(`/projects/${projectId}/stats/snapshots`);
  await moderator.getByRole('checkbox', { name: `Выбрать «${SNAPSHOT}» для сравнения` }).check();
  await moderator.getByRole('button', { name: 'Сравнить с текущим' }).click();
  await expect(moderator).toHaveURL(/\/stats\/compare/);
  const changes = moderator.getByRole('table');
  await expect(changes.getByRole('row').filter({ hasText: LEAF })).toContainText('изменён');
});

test('руководитель пресейла находит проект в портфеле и становится модератором', async ({ browser }) => {
  const head = await open(browser, seed.head);
  await head.goto('/portfolio');
  await head.getByRole('textbox', { name: 'Название или заказчик' }).fill(PROJECT);
  const row = head.getByRole('row').filter({ hasText: PROJECT });
  await expect(row).toHaveCount(1);
  await row.getByRole('button', { name: 'Стать модератором' }).click();
  await expect(head.getByText(`Вы модератор проекта «${PROJECT}». Модераторы получили уведомление`)).toBeVisible();

  const team = await api<{ items: { user: { id: string }; role: string }[] }>(
    head,
    'GET',
    `/projects/${projectId}/members`,
  );
  expect(team.items.some((m) => m.user.id === seed.head.id && m.role === 'moderator')).toBe(true);
});
