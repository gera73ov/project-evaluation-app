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
  const menu = moderator.getByRole('dialog', { name: /Экспорт/ });
  await expect(menu).toBeVisible();
  await expect(menu).toHaveCSS('opacity', '1'); // контраст считается после появления меню
  expect(await audit(moderator)).toEqual([]);
});

test('рабочий экран: 1366 px без горизонтальной прокрутки, уже — прокрутка дерева и сжатая полоса', async () => {
  const leafOf = () =>
    moderator
      .getByRole('treegrid', { name: 'Дерево оценки' })
      .locator('.vrow [role="row"]')
      .filter({ hasText: LEAF })
      .first();
  const scroller = moderator.locator('.tree-scroll');
  const top = moderator.locator('header.top');
  try {
    await moderator.setViewportSize({ width: 1366, height: 768 });
    await moderator.goto(`/projects/${projectId}`);
    await expect(leafOf()).toBeVisible();
    const wide = await scroller.evaluate((el) => el.scrollWidth - el.clientWidth);
    expect(wide).toBeLessThanOrEqual(0);
    await expect(top.getByText('Настройки', { exact: true })).toBeVisible();
    await expect(top.locator('.fig-p90')).toBeVisible();

    await moderator.setViewportSize({ width: 1024, height: 768 });
    await expect(top.locator('.fig-p90')).toBeHidden();
    await expect(top.locator('.fig-p80')).toHaveAttribute('title', /^P90 /);
    await expect(top.locator('.fig.quote')).toBeVisible();
    // подпись скрыта визуально, но остаётся в имени ссылки
    expect(
      await top.getByText('Настройки', { exact: true }).evaluate((el) => el.getBoundingClientRect().width),
    ).toBeLessThanOrEqual(1);
    await expect(top.getByRole('link', { name: /Настройки/ })).toBeVisible();

    expect(await scroller.evaluate((el) => el.scrollWidth - el.clientWidth)).toBeGreaterThan(0);
    const box = await scroller.boundingBox();
    await scroller.evaluate((el) => (el.scrollLeft = el.scrollWidth));
    const node = leafOf().locator('.td.node');
    await expect.poll(async () => Math.round((await node.boundingBox())?.x ?? -1)).toBe(Math.round(box?.x ?? 0));
    const head = moderator.locator('.tree-head .td.node');
    await expect.poll(async () => Math.round((await head.boundingBox())?.x ?? -1)).toBe(Math.round(box?.x ?? 0));
    const headE = moderator.locator('.tree-head [role="columnheader"]').nth(6);
    const rowE = leafOf().locator('.td.e');
    await expect
      .poll(
        async () => Math.round((await headE.boundingBox())?.x ?? 0) - Math.round((await rowE.boundingBox())?.x ?? 1),
      )
      .toBe(0);
    expect(await audit(moderator)).toEqual([]);
  } finally {
    await moderator.setViewportSize({ width: 1440, height: 900 });
  }
});

test('рабочий экран: обход клавиатурой — полоса, меню «Экспорт ▾», снимок, обсуждение строки', async () => {
  await moderator.goto(`/projects/${projectId}`);
  const tree = moderator.getByRole('treegrid', { name: 'Дерево оценки' });
  const leaf = tree.locator('.vrow [role="row"]').filter({ hasText: LEAF }).first();
  await expect(leaf).toBeVisible();

  // Tab с начала страницы доходит до ячейки O листа; у каждого шага видимый фокус и имя
  await moderator.locator('body').focus();
  const seen: string[] = [];
  for (let i = 0; i < 80; i++) {
    await moderator.keyboard.press('Tab');
    const info = await moderator.evaluate(() => {
      const el = document.activeElement as HTMLElement | null;
      if (!el || el === document.body) return null;
      const style = getComputedStyle(el);
      const rect = el.getBoundingClientRect();
      const name = (el.getAttribute('aria-label') || el.textContent?.trim() || el.getAttribute('title') || '').trim();
      const ring = style.outlineStyle !== 'none' && style.outlineWidth !== '0px';
      return { name, ring: ring || style.boxShadow !== 'none', visible: rect.width > 0 && rect.height > 0 };
    });
    expect(info, `шаг ${i + 1}: фокус потерян`).not.toBeNull();
    if (!info) break;
    expect(info.visible, `шаг ${i + 1} «${info.name}» не виден`).toBe(true);
    expect(info.name, `шаг ${i + 1}: нет имени`).not.toBe('');
    expect(info.ring, `шаг ${i + 1} «${info.name}»: нет видимого фокуса`).toBe(true);
    seen.push(info.name);
    if (/^O:/.test(info.name)) break;
  }
  expect(seen.at(-1) ?? '').toMatch(/^O:/);
  expect(seen.some((n) => /Экспорт/.test(n))).toBe(true);

  // «Экспорт ▾»: Enter открывает, Esc закрывает и возвращает фокус
  const exportBtn = moderator.getByRole('button', { name: /Экспорт/ });
  await exportBtn.focus();
  await moderator.keyboard.press('Enter');
  const menu = moderator.getByRole('dialog', { name: /Экспорт/ });
  await expect(menu).toBeVisible();
  await moderator.keyboard.press('Tab');
  await expect(menu.locator(':focus')).toHaveCount(1);
  await moderator.keyboard.press('Escape');
  await expect(menu).toBeHidden();
  await expect(exportBtn).toBeFocused();

  // «📷 Снимок»: фокус в диалоге, Esc закрывает и возвращает фокус
  const snapBtn = moderator.getByRole('button', { name: /Снимок/ });
  await snapBtn.focus();
  await moderator.keyboard.press('Enter');
  const dialog = moderator.getByRole('dialog', { name: /Снимок/ });
  await expect(dialog).toBeVisible();
  await expect(dialog.locator(':focus')).toHaveCount(1);
  await moderator.keyboard.press('Escape');
  await expect(dialog).toBeHidden();
  await expect(snapBtn).toBeFocused();

  // обсуждение строки: кнопка доступна с клавиатуры без наведения мыши
  await moderator.mouse.move(0, 0);
  const cell = leaf.getByRole('button', { name: /^O:/ });
  await cell.focus();
  const disc = leaf.getByRole('button', { name: /^(Обсуждение|Начать обсуждение)/ });
  for (let i = 0; i < 12 && !(await disc.evaluate((el) => el === document.activeElement)); i++) {
    await moderator.keyboard.press('Shift+Tab');
  }
  await expect(disc).toBeFocused();
  await expect(disc).toBeVisible();
  await moderator.keyboard.press('Enter');
  const panel = moderator.getByRole('region', { name: `Обсуждение: ${LEAF}` });
  await expect(panel).toBeVisible();
  expect(await audit(moderator)).toEqual([]);
});
