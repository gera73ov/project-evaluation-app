/**
 * QA-018 · сквозные сценарии ролей на настоящем API и WebSocket (SPEC 4.1, 4.5, 17.2, 11.14, CL-06).
 *
 * Сквозной процесс 4.1 на одном проекте: модератор заводит проект и команду (двое экспертов одной
 * дисциплины и пресейл) и запускает оценку; эксперт в первый рабочий день (4.5) входит и заполняет
 * первый лист — время «первый вход → первый заполненный лист» пишется в отчёт (метрика 1.3, GAP-04);
 * название листа — XSS-строка, и дерево, обсуждение и статистика показывают её текстом (CL-06);
 * множитель 12 даёт Σ E 72,0 и выделенную плашку «×12» (G-07); конфликт правки решается
 * «Оставить моё» (G-14); пресейл видит деньги и выгружает Excel «С деньгами», модератор делает
 * снимок; исключённый эксперт видит «Доступ к проекту отозван» (G-13).
 *
 * Отдельно: модератор с сессией без второго фактора видит «🔒 Подтвердите вход кодом» вместо денег и
 * после кода — ставки (G-19); руководитель пресейла видит в портфеле неактивную «Стать модератором» у
 * проекта в «Архиве», а API отвечает 409 (G-21). Данные — `scenarios/seed.py`. Сценарии идут по порядку.
 */
import { readFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import {
  expect,
  test,
  type Browser,
  type BrowserContext,
  type Download,
  type Locator,
  type Page,
} from '@playwright/test';

import { SCENARIOS_DATA_FILE } from '../global-setup';
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
  presale: Person;
  head: Person;
  moderator2: Person;
  phases: string[];
  disciplines: string[];
  discipline_names: string[];
  archived: { id: string; name: string };
  guarded: { id: string; session: string; csrf: string };
  password: string;
  totp: string;
}

const seed = JSON.parse(readFileSync(SCENARIOS_DATA_FILE, 'utf8')) as Seed;
const PROJECT = `E2E сквозной ${Date.now()}`;
/** CL-06: строка, которая выполнилась бы как HTML, должна остаться текстом везде. */
const XSS = '<img src=x onerror=alert(1)>';
const SNAPSHOT = 'v1 — КП отправлено';

test.describe.configure({ mode: 'serial' });

let lastStep = 0;
const contexts: BrowserContext[] = [];
/** CL-14 и CL-06: нарушений CSP и диалогов alert быть не должно ни у кого из участников. */
const problems: string[] = [];
let moderator: Page;
let expertA: Page;
let expertB: Page;
let projectId = '';
let leafId = '';

async function newPage(browser: Browser): Promise<Page> {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  contexts.push(context);
  const page = await context.newPage();
  page.on('console', (message) => {
    if (message.type() === 'error' && /Content Security Policy/i.test(message.text())) problems.push(message.text());
  });
  page.on('dialog', (dialog) => {
    problems.push(`dialog ${dialog.type()}: ${dialog.message()}`);
    void dialog.dismiss();
  });
  return page;
}

/** Вход паролем и, у кого подключён TOTP, кодом; шаг TOTP не повторяется. Возвращает время нажатия «Войти». */
async function signIn(page: Page, who: Person, withTotp: boolean): Promise<number> {
  await page.goto('/login');
  await page.getByLabel('Логин').fill(who.login);
  await page.getByLabel('Пароль').fill(seed.password);
  await spendLogin();
  const started = Date.now();
  await page.getByRole('button', { name: 'Войти' }).click();
  if (withTotp) await enterCode(page);
  await expect(page).not.toHaveURL(/\/login/);
  return started;
}

async function enterCode(page: Page): Promise<void> {
  while (currentStep() <= lastStep) await page.waitForTimeout(1000);
  lastStep = currentStep();
  await page.getByLabel('Цифра 1').pressSequentially(totp(seed.totp, lastStep));
}

async function api<T>(
  page: Page,
  method: string,
  path: string,
  data?: unknown,
  ok = true,
): Promise<T & { status: number }> {
  const csrf = (await page.context().cookies()).find((c) => c.name === '__Host-csrf')?.value ?? '';
  const response = await page.request.fetch(`/api/v1${path}`, { method, data, headers: { 'X-CSRF-Token': csrf } });
  const text = await response.text();
  if (ok) expect(response.ok(), `${method} ${path}: ${text}`).toBe(true);
  return { ...((text ? JSON.parse(text) : {}) as T), status: response.status() };
}

/** Текст всех XML-частей файла Office; openpyxl пишет кириллицу ссылками `&#1050;`. */
async function officeText(download: Download): Promise<string> {
  const path = await download.path();
  const script =
    'import html, sys, zipfile\n' +
    'z = zipfile.ZipFile(sys.argv[1])\n' +
    'parts = (z.read(n).decode("utf-8", "replace") for n in z.namelist() if n.endswith(".xml"))\n' +
    'print(html.unescape("\\n".join(parts)))';
  return execFileSync('python3', ['-I', '-c', script, path], { encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 });
}

const tree = (page: Page) => page.getByRole('treegrid', { name: 'Дерево оценки' });
const leafRow = (page: Page): Locator =>
  tree(page).getByText(XSS, { exact: true }).locator('xpath=ancestor::*[@role="row"][1]');

/** Нет ни одного элемента, который браузер построил бы из XSS-строки. */
async function expectNoInjectedImage(page: Page): Promise<void> {
  await expect(page.locator('img[src="x"]')).toHaveCount(0);
}

async function setCell(row: Locator, field: 'O' | 'R' | 'P', value: string): Promise<void> {
  await row.getByRole('button', { name: new RegExp(`^${field}:`) }).click();
  const input = row.getByRole('textbox', { name: field });
  await input.fill(value);
  await input.press('Enter');
  await expect(row.getByRole('button', { name: `${field}: ${value}` })).toBeVisible();
}

test.beforeAll(async ({ browser }) => {
  moderator = await newPage(browser);
  await signIn(moderator, seed.moderator, true);
});

test.afterEach(() => {
  expect(problems).toEqual([]);
});

test.afterAll(async () => {
  for (const context of contexts) await context.close();
});

test('4.1 модератор: проект, дисциплина, двое экспертов и пресейл, запуск оценки', async () => {
  const { project } = await api<{ project: { id: string } }>(moderator, 'POST', '/projects', {
    name: PROJECT,
    customer: 'ООО «Сквозной»',
    phase_ids: seed.phases,
  });
  projectId = project.id;
  await api(moderator, 'POST', `/projects/${projectId}/disciplines`, { discipline_id: seed.disciplines[0] });
  await api(moderator, 'PUT', `/projects/${projectId}/members`, {
    members: [
      { user_id: seed.moderator.id, role: 'moderator' },
      { user_id: seed.expert1.id, role: 'expert', discipline_id: seed.disciplines[0] },
      { user_id: seed.expert2.id, role: 'expert', discipline_id: seed.disciplines[0] },
      { user_id: seed.presale.id, role: 'presale' },
    ],
  });

  await moderator.goto(`/projects/${projectId}/settings`);
  await moderator.getByRole('button', { name: 'Статус проекта: Подготовка. Сменить' }).click();
  await moderator.getByRole('menuitem', { name: 'Запустить оценку' }).click();
  const start = moderator.getByRole('dialog', { name: 'Запустить оценку' });
  await expect(start).toContainText('Эксперты (2) получат письмо');
  await start.getByRole('button', { name: 'Запустить' }).click();
  await expect(moderator.getByRole('button', { name: 'Статус проекта: Оценка. Сменить' })).toBeVisible();
});

test('4.5 день эксперта: первый вход → первый заполненный лист; XSS-название — текстом в дереве', async ({
  browser,
}, testInfo) => {
  expertA = await newPage(browser);
  const firstLogin = await signIn(expertA, seed.expert1, false);
  // «Мои оценки» → проект (4.5, шаг 1)
  await expertA
    .getByRole('link', { name: new RegExp(PROJECT) })
    .first()
    .click();
  await expect(tree(expertA)).toBeVisible();

  const branch = tree(expertA).getByRole('row').filter({ hasText: 'В ветке пока ничего нет' }).first();
  await branch.getByRole('button', { name: /^Добавить рядом с/ }).click();
  await expertA
    .getByRole('menu')
    .getByRole('menuitem', { name: /Дочерний узел/ })
    .click();
  const title = tree(expertA).getByRole('textbox', { name: 'Название' });
  await title.fill(XSS);
  await title.press('Enter');
  const row = leafRow(expertA);
  await expect(row).toBeVisible();
  await setCell(row, 'O', '4');
  await setCell(row, 'R', '6');
  await setCell(row, 'P', '8');
  const filled = Date.now();

  const seconds = (filled - firstLogin) / 1000;
  testInfo.annotations.push({ type: 'метрика 1.3', description: `первый вход → первый лист: ${seconds.toFixed(1)} с` });
  console.log(`QA-018 метрика «первый вход → первый заполненный лист»: ${seconds.toFixed(1)} с`);

  await expect(tree(expertA).getByText(XSS, { exact: true })).toBeVisible();
  await expectNoInjectedImage(expertA);

  const { nodes } = await api<{ nodes: { id: string; title: string }[] }>(
    expertA,
    'GET',
    `/projects/${projectId}/tree`,
  );
  leafId = nodes.find((n) => n.title === XSS)?.id ?? '';
  expect(leafId).not.toBe('');
});

test('G-07 множитель 12: Σ E 72,0 и выделенная плашка «×12»', async () => {
  const row = leafRow(expertA);
  await row.getByRole('button', { name: 'Множитель ×N: 1' }).click();
  const input = row.getByRole('textbox', { name: 'Множитель ×N' });
  await input.fill('12');
  await input.press('Enter');
  const plaque = row.getByRole('button', { name: 'Множитель ×N: 12' });
  await expect(plaque).toHaveText('×12');
  // плашка ×1 приглушена (класс one), ×12 — выделена
  await expect(plaque).not.toHaveClass(/\bone\b/);
  await expect(row).toContainText('72,0');
});

test('G-14 конфликт правки: «Оставить моё» сохраняет значение эксперта, в истории две правки', async ({ browser }) => {
  expertB = await newPage(browser);
  await signIn(expertB, seed.expert2, false);
  await expertB.goto(`/projects/${projectId}`);
  await moderator.goto(`/projects/${projectId}`);
  // обе вкладки загрузили дерево и подписались на проект — иначе захват ячейки модератор не увидит
  await expect(leafRow(moderator)).toBeVisible();
  await expect(leafRow(expertB)).toBeVisible();
  await expect(moderator.getByText('Нет связи, правки не сохраняются')).toHaveCount(0);

  const mine = leafRow(expertB);
  await mine.getByRole('button', { name: /^R:/ }).click();
  const input = mine.getByRole('textbox', { name: 'R' });
  await input.fill('5');

  // значения в пределах O ≤ R ≤ P: неверный лист (R > P) не попал бы в статистику
  // другой участник успевает раньше: модератор перехватывает ячейку и сохраняет 7
  const locked = leafRow(moderator).getByLabel(`Сейчас редактирует ${seed.expert2.name}`);
  await expect(locked).toBeVisible({ timeout: 10_000 });
  await locked.click();
  await moderator.getByRole('button', { name: 'Всё равно править' }).click();
  const theirs = leafRow(moderator).getByRole('textbox', { name: 'R' });
  await theirs.fill('7');
  await theirs.press('Enter');
  await expect(leafRow(moderator).getByRole('button', { name: 'R: 7' })).toBeVisible({ timeout: 10_000 });

  await expect(input).toHaveValue('5');
  await input.press('Enter');
  const dialog = expertB.getByRole('dialog', { name: `Значение изменил ${seed.moderator.name}` });
  await expect(dialog).toBeVisible({ timeout: 10_000 });
  await expect(dialog).toContainText('Его: 7');
  await expect(dialog).toContainText('Ваше: 5');
  await dialog.getByRole('button', { name: 'Оставить моё' }).click();
  await expect(leafRow(expertB).getByRole('button', { name: 'R: 5' })).toBeVisible();
  await expect(leafRow(moderator).getByRole('button', { name: 'R: 5' })).toBeVisible({ timeout: 10_000 });

  const { items } = await api<{ items: { changes: Record<string, unknown> }[] }>(
    expertB,
    'GET',
    `/nodes/${leafId}/history`,
  );
  expect(items.filter((h) => 'r' in h.changes).length).toBeGreaterThanOrEqual(3); // 6, затем 7 и 5
});

test('CL-06 обсуждение листа: XSS-название и сообщение — текстом', async () => {
  const row = leafRow(expertA);
  await row.hover();
  await row.getByRole('button', { name: /^(Обсуждение|Начать обсуждение)/ }).click();
  const panel = expertA.getByRole('region', { name: `Обсуждение: ${XSS}` });
  await expect(panel).toBeVisible();
  await panel.getByRole('combobox', { name: 'Сообщение' }).fill(`Проверка ${XSS}`);
  await panel.getByRole('button', { name: 'Отправить' }).click();
  await expect(panel.getByText(`Проверка ${XSS}`)).toBeVisible();
  await expectNoInjectedImage(expertA);
});

test('CL-06 статистика: лист ×12 среди крупных — название текстом', async () => {
  await moderator.goto(`/projects/${projectId}/stats/candidates`);
  const large = moderator
    .getByRole('region', { name: /Крупные/ })
    .or(moderator.locator('section[aria-labelledby="det-large"]'));
  await expect(large.getByText(XSS, { exact: false }).first()).toBeVisible();
  await expectNoInjectedImage(moderator);
});

test('4.1 пресейл видит деньги и выгружает Excel «С деньгами»; модератор делает снимок', async ({ browser }) => {
  const presale = await newPage(browser);
  await signIn(presale, seed.presale, true);
  await presale.goto(`/projects/${projectId}/settings`);
  const money = presale.locator('section[aria-labelledby="set-money"]');
  await expect(money).toContainText('Ставки, ₽ за час');
  await expect(money).not.toContainText('Подтвердите вход кодом');

  await moderator.goto(`/projects/${projectId}`);
  await moderator.getByRole('button', { name: /Снимок$/ }).click();
  const dialog = moderator.getByRole('dialog', { name: 'Снимок проекта' });
  await dialog.getByRole('textbox', { name: 'Название' }).fill(SNAPSHOT);
  await dialog.getByRole('button', { name: 'Сделать снимок' }).click();
  await expect(moderator.getByText(`Снимок «${SNAPSHOT}» сохранён`)).toBeVisible();

  await presale.goto(`/projects/${projectId}`);
  await presale.getByRole('button', { name: /Экспорт/ }).click();
  const menu = presale.getByRole('dialog', { name: /Экспорт/ });
  const file = presale.waitForEvent('download');
  await menu.getByRole('button', { name: /С деньгами/ }).click();
  const xlsx = await file;
  expect(xlsx.suggestedFilename()).toMatch(/_деньги\.xlsx$/);
  const text = await officeText(xlsx);
  expect(text).toContain('Коммерческая тайна');
  expect(text).toContain(XSS);
});

test('G-13 исключение из команды: вкладка эксперта показывает «Доступ к проекту отозван»', async () => {
  await moderator.goto(`/projects/${projectId}/settings`);
  const team = moderator.getByRole('region', { name: 'Команда' });
  await team.getByRole('button', { name: `Убрать ${seed.expert2.name}` }).click();
  await expect(team.getByText(seed.expert2.name)).toHaveCount(0);
  const notice = expertB.getByRole('alert').filter({ hasText: 'Доступ к проекту отозван' });
  await expect(notice).toBeVisible({ timeout: 5_000 });
  await expect(tree(expertB)).toHaveCount(0);
});

test('G-19 сессия без второго фактора: «🔒 Подтвердите вход кодом», после кода — ставки', async ({
  browser,
  baseURL,
}) => {
  const page = await newPage(browser);
  const host = new URL(baseURL ?? 'https://localhost:8443').hostname;
  await page.context().addCookies([
    { name: '__Host-session', value: seed.guarded.session, domain: host, path: '/', secure: true, httpOnly: true },
    { name: '__Host-csrf', value: seed.guarded.csrf, domain: host, path: '/', secure: true },
  ]);
  await page.goto(`/projects/${seed.guarded.id}/settings`);
  const money = page.locator('section[aria-labelledby="set-money"]');
  await expect(money).toContainText('🔒 Подтвердите вход кодом');
  await expect(money).not.toContainText('Ставки, ₽ за час');
  const denied = await api<{ code: string }>(page, 'GET', `/projects/${seed.guarded.id}/money`, undefined, false);
  expect([denied.status, denied.code]).toEqual([403, 'TOTP_REQUIRED']);

  await money.getByRole('button', { name: 'Ввести код' }).click();
  const stepUp = page.getByRole('dialog', { name: 'Подтвердите вход кодом' });
  await expect(stepUp).toBeVisible();
  await enterCode(page);
  await expect(money).toContainText('Ставки, ₽ за час', { timeout: 10_000 });
  await expect(money).not.toContainText('Подтвердите вход кодом');
});

test('G-21 портфель: у проекта в «Архиве» «Стать модератором» неактивна, API — 409', async ({ browser }) => {
  const head = await newPage(browser);
  await signIn(head, seed.head, true);
  await head.goto('/portfolio');
  await head.getByRole('textbox', { name: 'Название или заказчик' }).fill(seed.archived.name);
  const row = head.getByRole('row').filter({ hasText: seed.archived.name });
  await expect(row).toHaveCount(1);
  await expect(row.getByRole('button', { name: `Стать модератором: ${seed.archived.name}` })).toBeDisabled();
  await expect(row).toContainText('Сначала восстановите проект');
  const join = await api(head, 'POST', `/projects/${seed.archived.id}/join-as-moderator`, {}, false);
  expect(join.status).toBe(409);
});
