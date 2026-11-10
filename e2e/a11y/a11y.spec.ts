/**
 * FE-080 · аудит доступности axe на готовых экранах (FR-UI-01..05, SPEC 11 «Цветовые обозначения»):
 * WCAG 2.1 A/AA, нарушения уровня serious и critical валят сценарий. Экраны: вход и восстановление
 * пароля; у модератора — «Мои оценки», новый проект, рабочий экран, настройки, корзина, журнал,
 * вкладки статистики, снимки и сравнение, профиль, портфель, документы заказчика, панель
 * обсуждения с закрытыми заметками и меню «Экспорт ▾»; у администратора — админка.
 *
 * Экраны системной части — после её серверной части.
 */
import AxeBuilder from '@axe-core/playwright';
import { readFileSync } from 'node:fs';
import { expect, test, type Browser, type BrowserContext, type Page } from '@playwright/test';

import { A11Y_DATA_FILE, runJson } from '../global-setup';
import { currentStep, totp } from '../auth/totp';
import { spendLogin } from '../auth/budget';

interface Person {
  id: string;
  login: string;
  name: string;
}

interface Seed {
  moderator: Person;
  admin: Person;
  phases: string[];
  disciplines: string[];
  password: string;
  totp: string;
}

const seed = JSON.parse(readFileSync(A11Y_DATA_FILE, 'utf8')) as Seed;
const FILL = process.env.E2E_A11Y_FILL_CMD ?? 'uv run --frozen python ../e2e/perf/fill.py';
const LEAF = 'Задача Модуль 1.1.1';

test.describe.configure({ mode: 'serial' });

let lastStep = 0;
const contexts: BrowserContext[] = [];
let moderator: Page;
let admin: Page;
let projectId = '';
let snapshotId = '';

async function open(browser: Browser, who: Person): Promise<Page> {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  contexts.push(context);
  const page = await context.newPage();
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

/** Нарушения serious/critical по WCAG 2.1 A/AA: правило, уровень, число узлов и первые селекторы. */
async function audit(page: Page): Promise<string[]> {
  await page.waitForLoadState('networkidle');
  await expect(page.locator('#root > :not(style)').first()).toBeVisible();
  const result = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze();
  await test
    .info()
    .attach('axe.json', { body: JSON.stringify(result.violations, null, 2), contentType: 'application/json' });
  return result.violations
    .filter((v) => v.impact === 'serious' || v.impact === 'critical')
    .map(
      (v) =>
        `${v.id} (${v.impact}, ${v.nodes.length}): ${v.nodes
          .slice(0, 3)
          .map((n) => n.target.join(' '))
          .join(' | ')}`,
    );
}

async function visit(page: Page, path: string): Promise<void> {
  await page.goto(path);
  expect(await audit(page)).toEqual([]);
}

test.beforeAll(async ({ browser }) => {
  moderator = await open(browser, seed.moderator);
  const { project } = await api<{ project: { id: string } }>(moderator, 'POST', '/projects', {
    name: `E2E доступность ${Date.now()}`,
    customer: 'ООО «Доступность»',
    phase_ids: seed.phases,
  });
  projectId = project.id;
  for (const id of seed.disciplines) {
    await api(moderator, 'POST', `/projects/${projectId}/disciplines`, { discipline_id: id });
  }
  runJson(`${FILL} ${projectId} 60`);
  await api(moderator, 'POST', `/projects/${projectId}/status`, { to: 'estimation' });
  const snapshot = await api<{ id: string }>(moderator, 'POST', `/projects/${projectId}/snapshots`, { name: 'v1' });
  snapshotId = snapshot.id;
  admin = await open(browser, seed.admin);
});

test.afterAll(async () => {
  for (const context of contexts) await context.close();
});

test('вход и восстановление пароля', async ({ browser }) => {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  contexts.push(context);
  const page = await context.newPage();
  for (const path of ['/login', '/password/forgot']) await visit(page, path);
});

for (const [name, path] of [
  ['«Мои оценки»', () => '/'],
  ['новый проект', () => '/projects/new'],
  ['рабочий экран', () => `/projects/${projectId}`],
  ['настройки проекта', () => `/projects/${projectId}/settings`],
  ['документы заказчика', () => `/projects/${projectId}/settings/documents`],
  ['корзина', () => `/projects/${projectId}/trash`],
  ['журнал проекта', () => `/projects/${projectId}/log`],
  ['сетка готовности', () => `/projects/${projectId}/stats`],
  ['итоги', () => `/projects/${projectId}/stats/totals`],
  ['доли', () => `/projects/${projectId}/stats/shares`],
  ['объёмы', () => `/projects/${projectId}/stats/volumes`],
  ['кандидаты', () => `/projects/${projectId}/stats/candidates`],
  ['теги', () => `/projects/${projectId}/stats/tags`],
  ['обсуждения', () => `/projects/${projectId}/stats/discussions`],
  ['вопросы заказчику', () => `/projects/${projectId}/stats/questions`],
  ['снимки', () => `/projects/${projectId}/stats/snapshots`],
  ['сравнение со снимком', () => `/projects/${projectId}/stats/compare?a=${snapshotId}`],
  ['профиль', () => '/profile'],
  ['портфель', () => '/portfolio'],
] as const) {
  test(`модератор: ${name}`, async () => {
    await visit(moderator, path());
  });
}

for (const [name, path] of [
  ['пользователи', '/admin/users'],
  ['справочники', '/admin/dictionaries'],
  ['производственный календарь', '/admin/calendar'],
  ['предложенные типы', '/admin/proposed-types'],
  ['реестр проектов', '/admin/registry'],
] as const) {
  test(`администратор: ${name}`, async () => {
    await visit(admin, path);
  });
}

test('рабочий экран: ввод оценки с клавиатуры', async () => {
  await moderator.goto(`/projects/${projectId}`);
  const tree = moderator.getByRole('treegrid', { name: 'Дерево оценки' });
  const leaf = tree.locator('.vrow [role="row"]').filter({ hasText: LEAF }).first();
  const cell = leaf.getByRole('button', { name: /^O:/ });
  await cell.focus();
  await moderator.keyboard.press('Enter');
  const input = leaf.getByRole('textbox', { name: 'O' });
  await expect(input).toBeFocused();
  await input.fill('5');
  await moderator.keyboard.press('Enter');
  await expect(leaf.getByRole('button', { name: 'O: 5' })).toBeVisible();
  expect(await audit(moderator)).toEqual([]);
});

test('рабочий экран: панель обсуждения с закрытыми заметками и меню «Экспорт ▾»', async () => {
  await moderator.goto(`/projects/${projectId}`);
  const leaf = moderator
    .getByRole('treegrid', { name: 'Дерево оценки' })
    .locator('.vrow [role="row"]')
    .filter({ hasText: LEAF })
    .first();
  await leaf.hover();
  await leaf.getByRole('button', { name: /^(Обсуждение|Начать обсуждение)/ }).click();
  const panel = moderator.getByRole('region', { name: `Обсуждение: ${LEAF}` });
  await panel.getByRole('tab', { name: /Заметки/ }).click();
  await expect(panel.getByRole('textbox', { name: 'Закрытая заметка' })).toBeVisible();
  expect(await audit(moderator)).toEqual([]);

  await moderator.getByRole('button', { name: /Экспорт/ }).click();
  await expect(moderator.getByRole('dialog', { name: /Экспорт/ })).toBeVisible();
  expect(await audit(moderator)).toEqual([]);
});
