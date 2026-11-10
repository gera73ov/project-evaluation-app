/**
 * Системная часть на настоящем API (FE-060…065, FE-094, FE-080): суперадминистратор видит состояние
 * служб и меню раздела, меняет политику безопасности со step-up и возвращает её обратно,
 * анонимизирует заблокированную учётку; аудитор ИБ находит эти события в журнале аудита и
 * выгружает CSV с грифом. Каждый экран раздела проходит аудит axe (WCAG 2.1 A/AA, serious/critical).
 * Настройка и проверка AD — на стенде с контроллером домена: локально его нет.
 */
import AxeBuilder from '@axe-core/playwright';
import { readFileSync } from 'node:fs';
import { expect, test, type Browser, type BrowserContext, type Page } from '@playwright/test';

import { SYSTEM_DATA_FILE } from '../global-setup';
import { currentStep, totp } from '../auth/totp';
import { spendLogin } from '../auth/budget';

interface Person {
  id: string;
  login: string;
  name: string;
}

interface Seed {
  superadmin: Person;
  auditor: Person;
  blocked: Person;
  password: string;
  totp: string;
}

const seed = JSON.parse(readFileSync(SYSTEM_DATA_FILE, 'utf8')) as Seed;

test.describe.configure({ mode: 'serial' });

let lastStep = 0;
const contexts: BrowserContext[] = [];
const cspErrors: string[] = [];
const pages = new Map<string, Page>();

async function nextCode(page: Page): Promise<string> {
  while (currentStep() <= lastStep) await page.waitForTimeout(1000);
  lastStep = currentStep();
  return totp(seed.totp, lastStep);
}

async function open(browser: Browser, who: Person): Promise<Page> {
  const known = pages.get(who.id);
  if (known) return known;
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, acceptDownloads: true });
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
  await page.getByLabel('Цифра 1').pressSequentially(await nextCode(page));
  await expect(page).not.toHaveURL(/\/login/);
  pages.set(who.id, page);
  return page;
}

/** Окно «Подтвердите действие»: пароль и новый код TOTP (FR-2FA-05). */
async function stepUp(page: Page): Promise<void> {
  const dialog = page.getByRole('dialog', { name: 'Подтвердите действие' });
  await expect(dialog).toBeVisible();
  await dialog.getByLabel('Пароль', { exact: true }).fill(seed.password);
  await spendLogin(1);
  await dialog.getByLabel('Цифра 1').pressSequentially(await nextCode(page));
  await expect(dialog).toBeHidden();
}

/** Step-up живёт несколько минут: окно появляется, только если срок прошёл. */
async function stepUpIfAsked(page: Page, done: ReturnType<Page['getByText']>): Promise<void> {
  const dialog = page.getByRole('dialog', { name: 'Подтвердите действие' });
  await expect(dialog.or(done)).toBeVisible();
  if (await dialog.isVisible()) await stepUp(page);
  await expect(done).toBeVisible();
}

async function audit(page: Page): Promise<string[]> {
  await page.waitForLoadState('networkidle');
  await expect(page.locator('#root > :not(style)').first()).toBeVisible();
  const result = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze();
  await test
    .info()
    .attach('axe.json', { body: JSON.stringify(result.violations, null, 2), contentType: 'application/json' });
  return result.violations
    .filter((v) => v.impact === 'serious' || v.impact === 'critical')
    .map((v) => `${v.id} (${v.impact}, ${v.nodes.length}): ${v.nodes.map((n) => n.target.join(' ')).join(' | ')}`);
}

test.afterEach(() => {
  expect(cspErrors).toEqual([]);
});

test.afterAll(async () => {
  for (const context of contexts) await context.close();
});

test('суперадминистратор: состояние служб и меню раздела', async ({ browser }) => {
  const page = await open(browser, seed.superadmin);
  await page.goto('/system');
  const menu = page.getByRole('navigation', { name: 'Разделы системы' });
  await expect(menu.getByRole('link')).toHaveCount(10);
  const list = page.getByRole('list', { name: 'Состояние системы' });
  await expect(list).toContainText('База данных');
  await expect(list.getByText('работает').first()).toBeVisible();
});

for (const [name, path] of [
  ['состояние системы', '/system'],
  ['аутентификация', '/system/auth'],
  ['безопасность', '/system/security'],
  ['почта', '/system/smtp'],
  ['сроки хранения', '/system/retention'],
  ['администраторы', '/system/admins'],
  ['аудиторы ИБ', '/system/auditors'],
  ['анонимизация', '/system/anonymize'],
  ['реестр проектов', '/system/projects'],
  ['журнал аудита', '/audit'],
] as const) {
  test(`суперадминистратор, axe: ${name}`, async ({ browser }) => {
    const page = await open(browser, seed.superadmin);
    await page.goto(path);
    expect(await audit(page)).toEqual([]);
  });
}

test('суперадминистратор: режим входа — через приложение', async ({ browser }) => {
  const page = await open(browser, seed.superadmin);
  await page.goto('/system/auth');
  await expect(page.getByText('Сейчас: через приложение')).toBeVisible();
  await expect(page.getByText(/Суперадминистраторы всегда входят паролем приложения/)).toBeVisible();
  await expect(page.getByRole('button', { name: 'Сохранить…' })).toBeDisabled();
});

test('суперадминистратор: политика TOTP со step-up и обратно', async ({ browser }) => {
  const page = await open(browser, seed.superadmin);
  await page.goto('/system/security');
  const card = page.getByRole('region', { name: 'Политики безопасности' });
  const moderator = card.getByRole('switch', { name: 'Модератор' });
  const save = card.getByRole('button', { name: 'Сохранить…' });
  await expect(save).toBeDisabled();
  await expect(moderator).toBeChecked();
  await moderator.evaluate((el: HTMLInputElement) => el.click()); // input Switch вне экрана, видна дорожка
  await expect(card.getByRole('alert')).toContainText('Второй фактор отключён для ролей: Модератор');
  await save.click();
  await stepUp(page);
  await expect(card.getByText('✓ Сохранено')).toBeVisible();

  await page.reload();
  await expect(moderator).not.toBeChecked();
  await moderator.evaluate((el: HTMLInputElement) => el.click());
  await save.click();
  await stepUpIfAsked(page, card.getByText('✓ Сохранено'));
  await page.reload();
  await expect(moderator).toBeChecked();
});

test('суперадминистратор: анонимизация заблокированной учётки', async ({ browser }) => {
  const page = await open(browser, seed.superadmin);
  await page.goto('/system/anonymize');
  const surname = seed.blocked.name.split(' ')[0] ?? '';
  await page.getByLabel('Поиск по ФИО или логину').fill(seed.blocked.login);
  const row = page.getByRole('row').filter({ hasText: surname });
  await expect(row).toHaveCount(1);
  await row.getByRole('button', { name: /^Анонимизировать / }).click();
  const dialog = page.getByRole('dialog', { name: /^Анонимизировать / });
  await dialog.getByRole('button', { name: 'Анонимизировать…' }).click();
  const asked = await page
    .getByRole('dialog', { name: 'Подтвердите действие' })
    .waitFor({ timeout: 3000 })
    .then(
      () => true,
      () => false,
    );
  if (asked) await stepUp(page);
  await expect(row).toHaveCount(0);
  await page.getByText('Анонимизированные', { exact: true }).click(); // SegmentedControl: input скрыт
  await page.getByLabel('Поиск по ФИО или логину').fill('');
  await expect(
    page
      .getByRole('row')
      .filter({ hasText: /Удалённый пользователь #\d+/ })
      .first(),
  ).toBeVisible();
});

test('аудитор ИБ: события в журнале аудита и выгрузка CSV с грифом', async ({ browser }) => {
  const page = await open(browser, seed.auditor);
  await page.goto('/audit');
  const table = page.getByRole('table');
  await expect(table).toContainText(seed.superadmin.login);
  await expect(table).toContainText('Анонимизация пользователя');
  await expect(table.getByRole('row').nth(1)).toBeVisible();

  const file = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Выгрузить CSV…' }).click();
  await stepUp(page);
  const csv = await file;
  expect(csv.suggestedFilename()).toMatch(/\.csv$/);
  const text = readFileSync(await csv.path(), 'utf8').replace(/^﻿/, '');
  expect(text.split('\n')[0]).toMatch(/^# Коммерческая тайна; /);
  expect(text).toContain(seed.superadmin.login);
});
