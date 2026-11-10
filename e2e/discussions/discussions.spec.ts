/**
 * FE-092 · обсуждения, вопросы заказчику, уведомления, заметки и документы на настоящем API/WS
 * (SPEC 4.5, 9.x, 11.4 №13–14, №18, 11.7, 11.11). Сценарии идут по порядку — «типовой день
 * эксперта»: эксперт под листом спрашивает @заказчик с «нужен ответ» и пишет «Допущение: …»;
 * пресейл выгружает вопросы в Word (FE-093) и вносит ответ заказчика; эксперт по уведомлению
 * переходит к строке, сужает вилку и отмечает ветку «Готово». Затем модератор: закрытая заметка
 * к листу, Excel «С деньгами» (FE-093), загрузка документа и ожидание проверки антивирусом.
 */
import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { expect, test, type Browser, type BrowserContext, type Download, type Page } from '@playwright/test';

import { DISCUSSIONS_DATA_FILE, runJson } from '../global-setup';
import { currentStep, totp } from '../auth/totp';
import { spendLogin } from '../auth/budget';

interface Person {
  id: string;
  login: string;
  name: string;
}

interface Seed {
  moderator: Person;
  expert: Person;
  presale: Person;
  phases: string[];
  disciplines: string[];
  discipline_names: string[];
  password: string;
  totp: string;
}

const seed = JSON.parse(readFileSync(DISCUSSIONS_DATA_FILE, 'utf8')) as Seed;
const FILL = process.env.E2E_DISCUSSIONS_FILL_CMD ?? 'uv run --frozen python ../e2e/perf/fill.py';
const PROJECT = `E2E обсуждения ${Date.now()}`;
/** Первый лист первой ветки после `fill.py`: O–R–P = 2–4–8. */
const LEAF = 'Задача Модуль 1.1.1';
const QUESTION = 'Есть ли у заказчика протокол обмена с 1С?';
const ASSUMPTION = 'Допущение: обмен через REST, формат согласуем';
const ANSWER = 'REST, спецификацию пришлём в декабре';
const NOTE = 'Заказчик торгуется по интеграции, скидка не больше 5%';
const DOCUMENT = 'ТЗ_e2e_портал.pdf';
const LOSS = 'Заказчик заморозил бюджет до весны';

test.describe.configure({ mode: 'serial' });

let lastStep = 0;
const contexts: BrowserContext[] = [];
const cspErrors: string[] = [];
const pages = new Map<string, Page>();
let projectId = '';

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
  while (currentStep() <= lastStep) await page.waitForTimeout(1000);
  lastStep = currentStep();
  await page.getByLabel('Цифра 1').pressSequentially(totp(seed.totp, lastStep));
  await expect(page).not.toHaveURL(/\/login/);
  pages.set(who.id, page);
  return page;
}

async function api<T>(page: Page, method: string, path: string, data?: unknown): Promise<T> {
  const csrf = (await page.context().cookies()).find((c) => c.name === '__Host-csrf')?.value ?? '';
  const response = await page.request.fetch(`/api/v1${path}`, { method, data, headers: { 'X-CSRF-Token': csrf } });
  const text = await response.text();
  expect(response.ok(), `${method} ${path}: ${text}`).toBe(true);
  return (text ? JSON.parse(text) : null) as T;
}

/** Текст всех XML-частей выгруженного файла Office (xlsx, docx — это zip); openpyxl пишет кириллицу ссылками `&#1050;`. */
async function officeText(download: Download): Promise<string> {
  const path = await download.path();
  const script =
    'import html, sys, zipfile\n' +
    'z = zipfile.ZipFile(sys.argv[1])\n' +
    'parts = (z.read(n).decode("utf-8", "replace") for n in z.namelist() if n.endswith(".xml"))\n' +
    'print(html.unescape("\\n".join(parts)))';
  return execFileSync('python3', ['-I', '-c', script, path], { encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 });
}

function leafRow(page: Page) {
  return page
    .getByRole('treegrid', { name: 'Дерево оценки' })
    .locator('.vrow [role="row"]')
    .filter({ hasText: LEAF })
    .first();
}

test.beforeAll(async ({ browser }) => {
  const moderator = await open(browser, seed.moderator);
  const { project } = await api<{ project: { id: string } }>(moderator, 'POST', '/projects', {
    name: PROJECT,
    customer: 'ООО «Дилеры»',
    phase_ids: seed.phases,
  });
  projectId = project.id;
  for (const id of seed.disciplines) {
    await api(moderator, 'POST', `/projects/${projectId}/disciplines`, { discipline_id: id });
  }
  runJson(`${FILL} ${projectId} 60`);
  await api(moderator, 'PUT', `/projects/${projectId}/members`, {
    members: [
      { user_id: seed.moderator.id, role: 'moderator' },
      { user_id: seed.expert.id, role: 'expert', discipline_id: seed.disciplines[0] },
      { user_id: seed.presale.id, role: 'presale' },
    ],
  });
  await api(moderator, 'POST', `/projects/${projectId}/status`, { to: 'estimation' });
});

test.afterEach(() => {
  expect(cspErrors).toEqual([]);
});

test.afterAll(async () => {
  for (const context of contexts) await context.close();
});

test('эксперт: вопрос @заказчик с «нужен ответ» под листом и «Допущение: …» в комментарии', async ({ browser }) => {
  const expert = await open(browser, seed.expert);
  await expert.goto(`/projects/${projectId}`);
  const leaf = leafRow(expert);
  await leaf.hover();
  await leaf.getByRole('button', { name: /^(Обсуждение|Начать обсуждение)/ }).click();
  const panel = expert.getByRole('region', { name: `Обсуждение: ${LEAF}` });
  const input = panel.getByRole('combobox', { name: 'Сообщение' });
  await input.fill(`${QUESTION} @заказ`);
  await expert
    .getByRole('listbox', { name: 'Адресаты' })
    .getByRole('option', { name: /@заказчик/ })
    .click();
  await panel.getByRole('checkbox', { name: 'нужен ответ' }).check();
  await panel.getByRole('button', { name: 'Отправить' }).click();
  await expect(panel.getByText('Открытый вопрос')).toBeVisible();
  await expect(panel).toContainText('адресат @заказчик');

  await leaf.getByRole('button', { name: 'Нажмите, чтобы добавить комментарий' }).click();
  const line = leaf.getByRole('textbox', { name: 'Строка комментария 1' });
  await line.fill(ASSUMPTION);
  await line.press('Enter');
  await expect(leaf).toContainText(ASSUMPTION);
});

test('пресейл: вопросы заказчику в Word, затем ответ заказчика', async ({ browser }) => {
  const presale = await open(browser, seed.presale);
  await presale.goto(`/projects/${projectId}/stats/questions`);
  const row = presale.getByRole('row').filter({ hasText: QUESTION });
  await expect(row).toBeVisible();
  const word = presale.waitForEvent('download');
  await presale.getByRole('button', { name: /Выгрузить в Word/ }).click();
  const docx = await word;
  expect(docx.suggestedFilename()).toMatch(/\.docx$/);
  expect(await officeText(docx)).toContain(QUESTION);
  await expect(row).toContainText(/отправлен/i);

  await row.getByRole('button', { name: 'Внести ответ заказчика' }).click();
  const dialog = presale.getByRole('dialog', { name: /Ответ заказчика на/ });
  await dialog.getByRole('textbox', { name: 'Текст ответа' }).fill(ANSWER);
  await dialog.getByRole('button', { name: 'Внести ответ' }).click();
  await expect(row).toContainText(ANSWER);
});

test('эксперт: уведомление ведёт к строке, вилка сужается, ветка «Готово»', async ({ browser }) => {
  const expert = await open(browser, seed.expert);
  await expert.goto('/');
  const bell = expert.getByRole('button', { name: /^Уведомления, непрочитанных: [1-9]/ });
  await expect(bell).toBeVisible();
  await bell.click();
  await expert.getByRole('region', { name: 'Мне' }).getByRole('button', { name: /Ответ/ }).first().click();
  await expect(expert).toHaveURL(new RegExp(`/projects/${projectId}\\?node=`));

  const leaf = leafRow(expert);
  await leaf.getByRole('button', { name: /^P:/ }).click();
  const p = leaf.getByRole('textbox', { name: 'P' });
  await p.fill('6');
  await p.press('Enter');
  await expect(leaf.getByRole('button', { name: 'P: 6' })).toBeVisible();

  // у отмеченной ветки кнопка пропадает (статус «Готово»), у второй ветки эксперта остаётся
  const done = expert.getByRole('button', { name: 'Отметить «Готово»' });
  const before = await done.count();
  expect(before).toBeGreaterThan(0);
  await expect(done.first()).toBeEnabled();
  await done.first().click();
  await expect(done).toHaveCount(before - 1);
});

test('модератор: закрытая заметка к листу; эксперт вкладки «Заметки» не видит', async ({ browser }) => {
  const moderator = await open(browser, seed.moderator);
  await moderator.goto(`/projects/${projectId}`);
  const leaf = leafRow(moderator);
  await leaf.hover();
  await leaf.getByRole('button', { name: /^(Обсуждение|Начать обсуждение)/ }).click();
  const panel = moderator.getByRole('region', { name: `Обсуждение: ${LEAF}` });
  await panel.getByRole('tab', { name: /Заметки/ }).click();
  await panel.getByRole('textbox', { name: 'Закрытая заметка' }).fill(NOTE);
  await panel.getByRole('button', { name: 'Добавить заметку' }).click();
  await expect(panel).toContainText(NOTE);
  await expect(panel.getByRole('tab', { name: /Заметки\s*1/ })).toBeVisible();

  const expert = await open(browser, seed.expert);
  await expert.goto(`/projects/${projectId}`);
  const own = leafRow(expert);
  await own.hover();
  await own.getByRole('button', { name: /^Обсуждение/ }).click();
  const view = expert.getByRole('region', { name: `Обсуждение: ${LEAF}` });
  await expect(view).toContainText(QUESTION);
  await expect(view.getByRole('tab')).toHaveCount(0);
  await expect(view).not.toContainText(NOTE);
});

test('модератор: Excel «С деньгами» с отметкой «Коммерческая тайна»', async ({ browser }) => {
  const moderator = await open(browser, seed.moderator);
  await moderator.goto(`/projects/${projectId}`);
  await moderator.getByRole('button', { name: /Экспорт/ }).click();
  const menu = moderator.getByRole('dialog', { name: /Экспорт/ });
  const file = moderator.waitForEvent('download');
  await menu.getByRole('button', { name: /С деньгами/ }).click();
  const xlsx = await file;
  expect(xlsx.suggestedFilename()).toMatch(/_деньги\.xlsx$/);
  const text = await officeText(xlsx);
  expect(text).toContain('Коммерческая тайна');
  expect(text).toContain(seed.moderator.name);
  expect(text).toContain(LEAF);
});

test('модератор: документ заказчика проверен антивирусом и скачивается', async ({ browser }) => {
  const moderator = await open(browser, seed.moderator);
  await moderator.goto(`/projects/${projectId}/settings/documents`);
  await moderator.getByLabel('Файл для загрузки').setInputFiles({
    name: DOCUMENT,
    mimeType: 'application/pdf',
    buffer: Buffer.from('%PDF-1.4\n% e2e\n1 0 obj << >> endobj\ntrailer << >>\n%%EOF\n'),
  });
  const row = moderator.getByRole('row').filter({ hasText: DOCUMENT });
  await expect(row).toContainText('✓ проверен', { timeout: 30_000 });
  const file = moderator.waitForEvent('download');
  await row.getByRole('button', { name: `Скачать ${DOCUMENT}` }).click();
  const pdf = await file;
  expect(pdf.suggestedFilename()).toBe(DOCUMENT);
  expect(readFileSync(await pdf.path(), 'latin1')).toMatch(/^%PDF-1\.4/);
});

test('модератор: результат пресейла «выигран» с суммой, затем «проигран» с причиной', async ({ browser }) => {
  const moderator = await open(browser, seed.moderator);
  await moderator.goto(`/projects/${projectId}/settings/outcome`);
  const section = moderator.getByRole('region', { name: 'Результат пресейла' });
  await section.getByText('выигран', { exact: true }).click(); // SegmentedControl: input скрыт
  const amount = section.getByLabel('Сумма договора');
  await amount.fill('2500000');
  await amount.blur();
  await section.getByRole('button', { name: 'Сохранить' }).click();
  await expect(section.getByText('✓ сохранено')).toBeVisible();
  const won = await api<{ outcome: string; money?: { contract_amount: string | null } }>(
    moderator,
    'GET',
    `/projects/${projectId}/outcome`,
  );
  expect(won.outcome).toBe('won');
  expect(Number(won.money?.contract_amount)).toBe(2_500_000);

  await moderator.reload();
  await expect(section.getByRole('radio', { name: 'выигран' })).toBeChecked();
  await section.getByText('проигран', { exact: true }).click(); // SegmentedControl: input скрыт
  await section.getByRole('textbox', { name: 'Причина проигрыша' }).click();
  await moderator.getByRole('option', { name: 'Другое' }).click();
  await section.getByRole('textbox', { name: 'Причина своими словами' }).fill(LOSS);
  await section.getByRole('button', { name: 'Сохранить' }).click();
  await expect(section.getByText('✓ сохранено')).toBeVisible();
  const lost = await api<{ outcome: string; loss_reason_text: string | null }>(
    moderator,
    'GET',
    `/projects/${projectId}/outcome`,
  );
  expect(lost.outcome).toBe('lost');
  expect(lost.loss_reason_text).toBe(LOSS);
});

test('модератор: журнал проекта — дисциплины, команда, статус, результат пресейла и сумма', async ({ browser }) => {
  const moderator = await open(browser, seed.moderator);
  await moderator.goto(`/projects/${projectId}/log`);
  const journal = moderator.getByRole('region', { name: 'Журнал проекта' });
  await expect(journal.getByText('Изменён результат пресейла').first()).toBeVisible();
  await expect(journal).toContainText('Результат пресейла: выигран → проигран');
  await expect(journal).toContainText(`Комментарий к причине: — → ${LOSS}`);
  await expect(journal).toContainText(/Сумма договора: — → 2\s?500\s?000|Сумма договора: — → 2500000/);
  await expect(journal).toContainText('Изменён статус');
  await expect(journal).toContainText('Изменена команда');
  await expect(journal.getByText('Изменён состав дисциплин').first()).toBeVisible();
  await expect(journal).toContainText(seed.discipline_names[0] ?? '');
  // подписи полей — из ru.json, без технических ключей
  await expect(journal).not.toContainText(/\b(loss_reason|contract_amount|outcome|rate:)/);
});
