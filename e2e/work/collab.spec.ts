/**
 * FE-091 · совместная работа в дереве на настоящем API и WebSocket (SPEC 8.2–8.5, FR-TREE-31…33,
 * TC-CONC-04): модератор создаёт проект, добавляет дисциплину и двух экспертов, запускает оценку;
 * эксперты и модератор — в отдельных браузерах. Новый узел и правка видны другому, захват ячейки
 * виден другому, после разрыва связи клиент догружает пропущенное, перехват модератором даёт
 * эксперту диалог конфликта, исключение из команды закрывает экран. Сценарии идут по порядку.
 */
import { readFileSync } from 'node:fs';
import {
  expect,
  test,
  type Browser,
  type BrowserContext,
  type Locator,
  type Page,
  type WebSocketRoute,
} from '@playwright/test';

import { WORK_DATA_FILE } from '../global-setup';
import { currentStep, totp } from '../auth/totp';
import { spendLogin } from '../auth/budget';

interface Person {
  id: string;
  login: string;
  name: string;
}

interface Seed {
  moderator: Person;
  expert1: Person;
  expert2: Person;
  phases: string[];
  disciplines: string[];
  discipline_names: string[];
  password: string;
  totp: string;
}

const seed = JSON.parse(readFileSync(WORK_DATA_FILE, 'utf8')) as Seed;
const LEAF = 'Настройка CI';

test.describe.configure({ mode: 'serial' });

let lastStep = 0;
const contexts: BrowserContext[] = [];
let moderator: Page;
let first: Page;
let second: Page;
let projectId = '';

/** Разрыв связи второго эксперта: открытые сокеты закрываются, новые не пускаются. */
const network = { offline: false, sockets: new Set<WebSocketRoute>() };

/** CL-14: нарушений CSP в консоли быть не должно ни у кого из участников. */
const cspErrors: string[] = [];

async function open(browser: Browser): Promise<Page> {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  contexts.push(context);
  const page = await context.newPage();
  page.on('console', (message) => {
    if (message.type() === 'error' && /Content Security Policy/i.test(message.text())) cspErrors.push(message.text());
  });
  return page;
}

async function signIn(page: Page, who: Person, withTotp = false): Promise<void> {
  await page.goto('/login');
  await page.getByLabel('Логин').fill(who.login);
  await page.getByLabel('Пароль').fill(seed.password);
  await spendLogin();
  await page.getByRole('button', { name: 'Войти' }).click();
  if (withTotp) {
    // сервер не принимает уже использованный шаг TOTP
    while (currentStep() <= lastStep) await page.waitForTimeout(1000);
    lastStep = currentStep();
    await page.getByLabel('Цифра 1').pressSequentially(totp(seed.totp, lastStep));
  }
  await expect(page).not.toHaveURL(/\/login/);
}

const tree = (page: Page) => page.getByRole('treegrid', { name: 'Дерево оценки' });
const row = (page: Page, title: string): Locator =>
  tree(page).getByText(title, { exact: true }).locator('xpath=ancestor::*[@role="row"][1]');

async function openProject(page: Page): Promise<void> {
  await page.goto(`/projects/${projectId}`);
  await expect(tree(page)).toBeVisible();
}

test.beforeAll(async ({ browser }) => {
  moderator = await open(browser);
  first = await open(browser);
  second = await open(browser);
  await second.routeWebSocket(/\/api\/v1\/ws/, (ws) => {
    if (network.offline) {
      void ws.close({ code: 1006 });
      return;
    }
    ws.connectToServer();
    network.sockets.add(ws);
  });
  await signIn(moderator, seed.moderator, true);
  await signIn(first, seed.expert1);
  await signIn(second, seed.expert2);
});

test.afterEach(() => {
  expect(cspErrors).toEqual([]);
});

test.afterAll(async () => {
  for (const context of contexts) await context.close();
});

test('модератор создаёт проект, добавляет дисциплину и экспертов, запускает оценку', async () => {
  const discipline = seed.discipline_names[0] ?? '';
  await moderator.goto('/projects/new');
  await expect(moderator.getByRole('heading', { name: 'Новый проект' })).toBeVisible();
  await moderator.getByRole('textbox', { name: /Название/ }).fill(`E2E совместная ${Date.now()}`);
  await moderator.getByRole('textbox', { name: /Заказчик/ }).fill('ООО «Тест»');
  await moderator.getByRole('button', { name: 'Создать' }).click();
  await expect(moderator).toHaveURL(/\/projects\/[^/]+\/settings$/);
  projectId = new URL(moderator.url()).pathname.split('/')[2] ?? '';

  const team = moderator.getByRole('region', { name: 'Команда' });
  await team.getByRole('button', { name: '+ Добавить дисциплину' }).click();
  const add = moderator.getByRole('dialog', { name: 'Добавить дисциплину' });
  await add.getByRole('textbox', { name: 'Дисциплина' }).click();
  await moderator.getByRole('option', { name: discipline, exact: true }).click();
  await add.getByRole('button', { name: 'Добавить дисциплину' }).click();
  await expect(add).toBeHidden();

  for (const expert of [seed.expert1, seed.expert2]) {
    await team.getByRole('button', { name: `Добавить эксперта: ${discipline}` }).click();
    const pick = moderator.getByRole('dialog', { name: 'Добавить эксперта' });
    await pick.getByRole('textbox', { name: 'ФИО' }).fill(expert.name);
    await pick.getByRole('button', { name: new RegExp(expert.name) }).click();
    await expect(team.getByText(expert.name)).toBeVisible();
  }

  await moderator.getByRole('button', { name: 'Статус проекта: Подготовка. Сменить' }).click();
  await moderator.getByRole('menuitem', { name: 'Запустить оценку' }).click();
  const start = moderator.getByRole('dialog', { name: 'Запустить оценку' });
  await expect(start).toContainText('Эксперты (2) получат письмо');
  await start.getByRole('button', { name: 'Запустить' }).click();
  await expect(moderator.getByRole('button', { name: 'Статус проекта: Оценка. Сменить' })).toBeVisible();

  await openProject(first);
  await openProject(second);
});

test('новый лист эксперта сразу появляется у второго эксперта', async () => {
  const discipline = tree(first).getByRole('row').filter({ hasText: 'В ветке пока ничего нет' }).first();
  await discipline.getByRole('button', { name: /^Добавить рядом с/ }).click();
  await first
    .getByRole('menu')
    .getByRole('menuitem', { name: /Дочерний узел/ })
    .click();
  const title = tree(first).getByRole('textbox', { name: 'Название' });
  await title.fill(LEAF);
  await title.press('Enter');
  await expect(row(second, LEAF)).toBeVisible({ timeout: 10_000 });
});

test('захват ячейки виден другому, правка приходит с подсветкой', async () => {
  await row(second, LEAF).getByRole('button', { name: /^O:/ }).click();
  await expect(row(first, LEAF).getByLabel(`Сейчас редактирует ${seed.expert2.name}`)).toBeVisible({
    timeout: 10_000,
  });
  const input = row(second, LEAF).getByRole('textbox', { name: 'O' });
  await input.fill('8');
  await input.press('Enter');
  await expect(row(first, LEAF).getByRole('button', { name: 'O: 8' })).toBeVisible({ timeout: 10_000 });
  await expect(row(first, LEAF)).toHaveClass(/changed/);
  await expect(row(first, LEAF).getByLabel(/Сейчас редактирует/)).toHaveCount(0);
});

test('разрыв связи: полоса «Нет связи», после восстановления — пропущенные правки', async () => {
  network.offline = true;
  for (const ws of network.sockets) await ws.close({ code: 4000, reason: 'e2e' });
  network.sockets.clear();
  await expect(second.getByText('Нет связи, правки не сохраняются')).toBeVisible({ timeout: 15_000 });

  await row(first, LEAF).getByRole('button', { name: /^R:/ }).click();
  const input = row(first, LEAF).getByRole('textbox', { name: 'R' });
  await input.fill('12');
  await input.press('Enter');
  await expect(row(first, LEAF).getByRole('button', { name: 'R: 12' })).toBeVisible();
  await expect(row(second, LEAF).getByRole('button', { name: 'R: 12' })).toHaveCount(0);

  network.offline = false;
  await expect(row(second, LEAF).getByRole('button', { name: 'R: 12' })).toBeVisible({ timeout: 20_000 });
  await expect(second.getByText('Нет связи, правки не сохраняются')).toHaveCount(0);
});

test('перехват модератором: эксперт получает диалог конфликта и выбирает «Принять»', async () => {
  await openProject(moderator);
  await row(first, LEAF).getByRole('button', { name: /^P:/ }).click();
  const mine = row(first, LEAF).getByRole('textbox', { name: 'P' });
  await mine.fill('20');

  const locked = row(moderator, LEAF).getByLabel(`Сейчас редактирует ${seed.expert1.name}`);
  await expect(locked).toBeVisible({ timeout: 10_000 });
  await locked.click();
  await moderator.getByRole('button', { name: 'Всё равно править' }).click();
  const theirs = row(moderator, LEAF).getByRole('textbox', { name: 'P' });
  await theirs.fill('24');
  await theirs.press('Enter');
  await expect(row(moderator, LEAF).getByRole('button', { name: 'P: 24' })).toBeVisible({ timeout: 10_000 });

  // несохранённый ввод эксперта остаётся в поле до конфликта (FR-TREE-31)
  await expect(mine).toHaveValue('20');
  await mine.press('Enter');
  const dialog = first.getByRole('dialog', { name: `Значение изменил ${seed.moderator.name}` });
  await expect(dialog).toBeVisible({ timeout: 10_000 });
  await expect(dialog).toContainText('Его: 24');
  await expect(dialog).toContainText('Ваше: 20');
  await dialog.getByRole('button', { name: 'Принять' }).click();
  await expect(row(first, LEAF).getByRole('button', { name: 'P: 24' })).toBeVisible();
});

test('исключение из команды закрывает экран у исключённого', async () => {
  await moderator.goto(`/projects/${projectId}/settings`);
  const team = moderator.getByRole('region', { name: 'Команда' });
  await team.getByRole('button', { name: `Убрать ${seed.expert2.name}` }).click();
  await expect(team.getByText(seed.expert2.name)).toHaveCount(0);
  const notice = second.getByRole('alert').filter({ hasText: 'Доступ к проекту отозван' });
  await expect(notice).toBeVisible({ timeout: 15_000 });
  await expect(notice).toContainText('Модератор исключил вас из команды проекта');
  await expect(tree(second)).toHaveCount(0);
  await notice.getByRole('link', { name: '← К моим оценкам' }).click();
  await expect(second).toHaveURL('/');
});
