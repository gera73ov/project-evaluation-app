/**
 * FE-094 · админка администратора на настоящем API (SPEC 7.5, FR-ADM-01…08): пользователи
 * (создание, роли, блокировка, сброс пароля со step-up), справочники и «Пороги и проценты»,
 * производственный календарь, предложенные типы, реестр проектов (проект без модератора после
 * блокировки, назначение модератора, режим поддержки). Сценарии идут по порядку.
 *
 * Системная часть (суперадминистратор, AD, журнал аудита) — после серверной части SYS-API.
 */
import { readFileSync } from 'node:fs';
import { expect, test, type Browser, type BrowserContext, type Page } from '@playwright/test';

import { ADMIN_DATA_FILE } from '../global-setup';
import { currentStep, totp } from '../auth/totp';

interface Person {
  id: string;
  login: string;
  name: string;
}

interface Seed {
  admin: Person;
  user: Person;
  moderator: Person;
  moderator2: Person;
  phases: string[];
  suffix: string;
  password: string;
  totp: string;
}

const seed = JSON.parse(readFileSync(ADMIN_DATA_FILE, 'utf8')) as Seed;
const PROJECT = `E2E реестр ${seed.suffix}`;
const LOCAL_TYPE = `E2E тип ${seed.suffix}`;

test.describe.configure({ mode: 'serial' });

/** Последний принятый шаг TOTP по логину: сервер не принимает шаг повторно. */
const lastStep = new Map<string, number>();
const contexts: BrowserContext[] = [];
const cspErrors: string[] = [];
let admin: Page;

/** Пользователи этого прогона: на общем стенде их легко не найти на первой странице списка. */
async function onlyThisRun(page: Page): Promise<void> {
  await page.getByRole('textbox', { name: 'ФИО или логин' }).fill(seed.suffix);
  // поиск применяется с задержкой: ждём, пока в таблице останутся только строки этого прогона
  await expect(page.getByRole('table').getByRole('row').filter({ hasNotText: seed.suffix })).toHaveCount(1);
}

async function code(page: Page, login: string): Promise<string> {
  while (currentStep() <= (lastStep.get(login) ?? 0)) await page.waitForTimeout(1000);
  const step = currentStep();
  lastStep.set(login, step);
  return totp(seed.totp, step);
}

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
  await page.getByRole('button', { name: 'Войти' }).click();
  await page.getByLabel('Цифра 1').pressSequentially(await code(page, who.login));
  await expect(page).not.toHaveURL(/\/login/);
  return page;
}

/** Вызов API из сессии страницы: CSRF-токен из cookie, как у SPA. */
async function api<T>(page: Page, method: string, path: string, data?: unknown): Promise<T> {
  const csrf = (await page.context().cookies()).find((c) => c.name === '__Host-csrf')?.value ?? '';
  const response = await page.request.fetch(`/api/v1${path}`, { method, data, headers: { 'X-CSRF-Token': csrf } });
  const text = await response.text();
  expect(response.ok(), `${method} ${path}: ${text}`).toBe(true);
  return (text ? JSON.parse(text) : null) as T;
}

test.beforeAll(async ({ browser }) => {
  // модератор заводит проект и локальный тип узла — они понадобятся реестру и «Предложенным типам»
  const moderator = await open(browser, seed.moderator);
  const { project } = await api<{ project: { id: string } }>(moderator, 'POST', '/projects', {
    name: PROJECT,
    customer: 'ООО «Реестр»',
    phase_ids: seed.phases,
  });
  await api(moderator, 'POST', `/projects/${project.id}/node-types`, { name: LOCAL_TYPE, icon: 'module' });
  admin = await open(browser, seed.admin);
});

test.afterEach(() => {
  expect(cspErrors).toEqual([]);
});

test.afterAll(async () => {
  for (const context of contexts) await context.close();
});

test('пользователи: создание с ролью, роли, сброс пароля с подтверждением кодом', async () => {
  await admin.goto('/admin/users');
  await onlyThisRun(admin);
  const table = admin.getByRole('table');
  await admin.getByRole('button', { name: '+ Добавить' }).click();
  const login = `e2e.new.${seed.suffix}`;
  await admin.getByLabel(/Логин/).fill(login);
  await admin.getByRole('textbox', { name: /^ФИО\s*\*?$/ }).fill(`Новиков Н. ${seed.suffix}`);
  await admin.getByRole('checkbox', { name: 'Модератор' }).click();
  await admin.getByRole('button', { name: 'Создать' }).click();
  await expect(admin.getByText('Пользователь создан')).toBeVisible();
  await expect(admin.getByText(/\/activate\?token=/)).toBeVisible();
  await expect(table.getByText(login)).toBeVisible();

  await table.getByRole('button', { name: seed.user.name }).click();
  await admin.getByRole('checkbox', { name: 'Пресейл', exact: true }).click();
  await admin.getByRole('button', { name: 'Сохранить роли' }).click();
  await expect(admin.getByText('✓ Роли сохранены')).toBeVisible();

  await admin.getByRole('button', { name: 'Сбросить пароль' }).click();
  await admin
    .getByRole('dialog', { name: /^Сбросить пароль/ })
    .getByRole('button', { name: 'Сбросить пароль' })
    .click();
  const stepUp = admin.getByRole('dialog', { name: 'Подтвердите действие' });
  await stepUp.getByLabel('Пароль', { exact: true }).fill(seed.password);
  await stepUp.getByLabel('Цифра 1').pressSequentially(await code(admin, seed.admin.login));
  await expect(admin.getByText('✓ Пароль сброшен')).toBeVisible();
  await expect(admin.getByText(/\/password\/reset\?token=/)).toBeVisible();
  await expect(admin).toHaveURL(/\/admin\/users/);
});

test('справочники: фаза и дисциплина создаются и удаляются, «Пороги и проценты» сохраняются', async () => {
  for (const kind of ['phases', 'disciplines'] as const) {
    await admin.goto(`/admin/dictionaries/${kind}`);
    const table = admin.getByRole('table');
    await expect(table).toBeVisible();
    await admin.getByRole('button', { name: '+ Добавить' }).click();
    const name = `E2E ${kind} ${seed.suffix}`;
    await admin.getByRole('textbox', { name: /^Название/ }).fill(name);
    if (kind === 'disciplines') await admin.getByRole('textbox', { name: /^Короткое название/ }).fill('E2E');
    await admin.getByRole('button', { name: 'Создать' }).click();
    await expect(admin.getByText('✓ Сохранено')).toBeVisible();
    await table.getByRole('button', { name }).click();
    await admin.getByRole('button', { name: 'Удалить' }).click();
    await admin
      .getByRole('dialog', { name: /^Удалить/ })
      .getByRole('button', { name: 'Удалить' })
      .click();
    await expect(table.getByRole('button', { name })).toHaveCount(0);
  }
  await admin.goto('/admin/dictionaries/method');
  await admin.getByRole('button', { name: 'Сохранить' }).click();
  await expect(admin.getByText('✓ Сохранено')).toBeVisible();
});

test('производственный календарь: правка дня сохраняется и возвращается обратно', async () => {
  await admin.goto('/admin/calendar');
  const year = new Date().getFullYear();
  const march = admin.getByRole('region', { name: `Март ${year}` });
  const saturday = march.getByRole('button', { name: /^7 марта, / });
  const before = (await saturday.getAttribute('aria-label')) ?? '';
  for (let round = 0; round < 2; round += 1) {
    await saturday.click();
    await admin.getByRole('button', { name: 'Сохранить правки' }).click();
    await expect(admin.getByText('✓ Правки календаря сохранены')).toBeVisible();
  }
  await admin.reload();
  await expect(saturday).toHaveAttribute('aria-label', before);
});

test('предложенный тип из проекта отклоняется и уходит из списка', async () => {
  await admin.goto('/admin/proposed-types');
  const table = admin.getByRole('table');
  await expect(table.getByText(LOCAL_TYPE)).toBeVisible();
  await table.getByRole('button', { name: `Отклонить «${LOCAL_TYPE}»` }).click();
  await admin
    .getByRole('dialog', { name: new RegExp(`Отклонить «${LOCAL_TYPE}»`) })
    .getByRole('button', { name: 'Отклонить' })
    .click();
  // остаётся только сообщение о решении; в списке типа больше нет
  await expect(admin.getByRole('table').getByText(LOCAL_TYPE)).toHaveCount(0);
});

test('реестр: блокировка модератора, назначение нового, режим поддержки', async () => {
  await admin.goto('/admin/users');
  await onlyThisRun(admin);
  await admin.getByRole('table').getByRole('button', { name: seed.moderator.name }).click();
  await admin.getByRole('button', { name: 'Заблокировать' }).click();
  await admin
    .getByRole('dialog', { name: /^Заблокировать/ })
    .getByRole('button', { name: 'Заблокировать' })
    .click();
  await expect(admin.getByText('✓ Пользователь заблокирован')).toBeVisible();

  await admin.goto('/admin/registry');
  await admin.getByRole('checkbox', { name: 'Проекты без модератора' }).click();
  const row = admin.getByRole('table').getByRole('row').filter({ hasText: PROJECT });
  await expect(row).toContainText(`${seed.moderator.name} · заблокирован`);
  await expect(row).toContainText(/без модератора \d+ д/);

  await admin.getByRole('button', { name: `Передать или добавить модератора «${PROJECT}»` }).click();
  const transfer = admin.getByRole('dialog', { name: `Модераторы проекта «${PROJECT}»` });
  await expect(transfer.getByText('Проект нельзя оставить без модератора.')).toBeVisible();
  await transfer.getByRole('textbox', { name: /Добавить модератора/ }).fill(seed.moderator2.name);
  await admin.getByRole('option', { name: new RegExp(seed.moderator2.name) }).click();
  await transfer.getByRole('button', { name: 'Сохранить' }).click();
  await expect(row).toHaveCount(0);

  await admin.getByRole('checkbox', { name: 'Проекты без модератора' }).click();
  await admin.getByRole('button', { name: `Открыть «${PROJECT}» в режиме поддержки` }).click();
  const support = admin.getByRole('dialog', { name: `Режим поддержки: «${PROJECT}»` });
  await support.getByRole('textbox', { name: /Причина/ }).fill('Проверка итогов по обращению заказчика');
  await support.getByRole('button', { name: 'Открыть проект' }).click();
  await expect(admin.getByText(/Режим поддержки · только чтение/)).toBeVisible();
  await expect(admin.getByRole('treegrid', { name: 'Дерево оценки' })).toBeVisible();
  // только чтение и без денег (FR-ADM-06): ни кнопок добавления узлов, ни сумм
  await expect(admin.getByRole('button', { name: /^Добавить рядом с/ })).toHaveCount(0);
  await expect(admin.getByText(/₽/)).toHaveCount(0);
});
