/**
 * FE-094 · установка с нуля и вход через AD на стенде с Samba AD (SPEC 7.1, 11.2, FR-SA-01…03,
 * FR-AUTH-AD-01…05, FR-AUTH-AD-10, FR-2FA-04): `estimator create-superadmin` → ссылка установки
 * пароля → обязательное подключение TOTP → мастер первичной настройки со способом входа «Через Active
 * Directory» (подключение LDAPS с сертификатом УЦ, «Проверить подключение», группа доступа, «Проверить
 * вход») → первый администратор из каталога → «Приложение готово». Затем администратор из AD входит
 * паролем каталога и подключает TOTP, пользователь из группы доступа появляется при первом входе, а
 * суперадминистратор по-прежнему входит паролем приложения.
 *
 * База перед сценариями очищается (`ad/reset.py`), поэтому набор идёт последним: проект `ad` в
 * playwright.config.ts зависит от остальных. После сценариев база снова пустая (`reset.py --plain`):
 * повторный прогон на том же стенде начинается в режиме «Приложение».
 *
 * Данные каталога — deploy/samba-ad/seed.sh: `moderator.one` и `expert.one` в группе est-access,
 * пароль у всех SAMBA_TEST_PASSWORD. Учётки Samba сценарии не меняют.
 */
import { randomBytes } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { expect, test, type Browser, type BrowserContext, type Page } from '@playwright/test';

import { runJson } from '../global-setup';
import { currentStep, totp } from '../auth/totp';
import { spendLogin } from '../auth/budget';

const ROOT = fileURLToPath(new URL('../../', import.meta.url));

/** Значение из .env стенда, если переменная окружения не задана. */
function fromEnvFile(key: string): string {
  try {
    const line = readFileSync(`${ROOT}.env`, 'utf8')
      .split('\n')
      .find((l) => l.startsWith(`${key}=`));
    return line?.slice(key.length + 1).trim() ?? '';
  } catch {
    return '';
  }
}

const RESET = process.env.E2E_AD_RESET_CMD ?? 'uv run --frozen python ../e2e/ad/reset.py';
const AD_PASSWORD = process.env.E2E_AD_PASSWORD ?? fromEnvFile('SAMBA_TEST_PASSWORD');
const CA = process.env.E2E_AD_CA ?? `${ROOT}deploy/compose/certs/ca.crt`;
const CONTROLLER = process.env.E2E_AD_CONTROLLER ?? 'dc1.test.estimator.local:636';
const BASE_DN = 'OU=Estimator,DC=test,DC=estimator,DC=local';
const BIND_DN = `CN=svc-estimator,OU=Service,${BASE_DN}`;
const ACCESS = `CN=est-access,OU=Groups,${BASE_DN}`;

interface Account {
  login: string;
  password: string;
  secret: string;
  lastStep: number;
}

// Логин суперадминистратора — e2e-fe-sa-<hex>, а политика запрещает пароль с частью логина от 3 символов:
// в случайном hex изредка попадалось «e2e». Поэтому буквы g…v вместо цифр hex.
const randomLetters = (bytes: number): string =>
  randomBytes(bytes)
    .toString('hex')
    .replace(/[0-9a-f]/g, (c) => 'ghijklmnopqrstuv'[parseInt(c, 16)]);
const sa: Account = { login: '', password: `Qw9-${randomLetters(16)}`, secret: '', lastStep: 0 };
const admin: Account = { login: 'moderator.one', password: AD_PASSWORD, secret: '', lastStep: 0 };
const expert = { login: 'expert.one', password: AD_PASSWORD };
let activation = '';

test.describe.configure({ mode: 'serial' });

const contexts: BrowserContext[] = [];
const cspErrors: string[] = [];
let root: Page;

/** Код следующего шага TOTP: сервер не принимает шаг, не больший уже принятого. */
async function nextCode(page: Page, who: Account): Promise<string> {
  while (currentStep() <= who.lastStep) await page.waitForTimeout(1000);
  who.lastStep = currentStep();
  return totp(who.secret, who.lastStep);
}

async function newPage(browser: Browser): Promise<Page> {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  contexts.push(context);
  const page = await context.newPage();
  page.on('console', (message) => {
    if (message.type() === 'error' && /Content Security Policy/i.test(message.text())) cspErrors.push(message.text());
  });
  return page;
}

async function signIn(page: Page, login: string, password: string, subtitle: string): Promise<void> {
  await page.goto('/login');
  await expect(page.getByText(subtitle)).toBeVisible();
  await page.getByLabel('Логин').fill(login);
  await page.getByLabel('Пароль').fill(password);
  await spendLogin();
  await page.getByRole('button', { name: 'Войти' }).click();
}

/** Обязательное подключение TOTP (FR-2FA-04): секрет с экрана, код, резервные коды, «Продолжить». */
async function enrollTotp(page: Page, who: Account): Promise<void> {
  await expect(page).toHaveURL('/enroll-totp');
  who.secret = (await page.getByLabel('Секрет').textContent())?.trim() ?? '';
  expect(who.secret).toMatch(/^[A-Z2-7]{16,}$/);
  await page.getByLabel('Цифра 1').pressSequentially(await nextCode(page, who));
  await expect(page.getByLabel('Резервные коды').locator('span')).toHaveCount(10);
  await page.getByRole('button', { name: 'Продолжить' }).click();
}

/** Окно «Подтвердите действие»: пароль приложения и новый код TOTP (FR-2FA-05). */
async function stepUp(page: Page, who: Account): Promise<void> {
  const dialog = page.getByRole('dialog', { name: 'Подтвердите действие' });
  await expect(dialog).toBeVisible();
  await dialog.getByLabel('Пароль', { exact: true }).fill(who.password);
  await spendLogin(1);
  await dialog.getByLabel('Цифра 1').pressSequentially(await nextCode(page, who));
  await expect(dialog).toBeHidden();
}

const next = (page: Page) => page.getByRole('button', { name: 'Сохранить и продолжить' }).click();

test.beforeAll(() => {
  expect(AD_PASSWORD, 'нужен SAMBA_TEST_PASSWORD (E2E_AD_PASSWORD или .env стенда)').not.toBe('');
  const out = JSON.parse(runJson(RESET)) as { login: string; link: string };
  sa.login = out.login;
  activation = out.link;
});

test.afterEach(() => {
  expect(cspErrors).toEqual([]);
});

test.afterAll(async () => {
  for (const context of contexts) await context.close();
  runJson(`${RESET} --plain`);
});

test('суперадминистратор из консоли: ссылка установки пароля, вход и подключение TOTP', async ({ browser }) => {
  root = await newPage(browser);
  await root.goto(activation);
  await expect(root.getByRole('heading', { name: 'Установка пароля' })).toBeVisible();
  await root.getByLabel('Новый пароль').fill(sa.password);
  await root.getByLabel('Повторите пароль').fill(sa.password);
  await root.getByRole('button', { name: 'Установить пароль' }).click();
  await expect(root.getByText('Пароль установлен. Теперь можно войти')).toBeVisible();

  await signIn(root, sa.login, sa.password, 'Учётная запись приложения');
  await enrollTotp(root, sa);
  // пока мастер не пройден, раздел «Система» ведёт в него
  await root.goto('/system');
  await expect(root).toHaveURL('/setup');
  await expect(root.getByRole('heading', { name: 'Первичная настройка' })).toBeVisible();
});

test('мастер: адрес, почта, вход через Active Directory с обеими проверками, политики', async () => {
  const steps = root.getByRole('list', { name: 'Шаги настройки' });

  await root.getByLabel('Адрес приложения').fill(new URL(root.url()).origin);
  await next(root);
  await expect(steps.getByRole('button', { name: /Почта/ })).toHaveAttribute('aria-current', 'step');
  // SMTP-ловушка стенда (Mailpit); письма со ссылками сценарию не нужны
  await root.getByLabel('Сервер').fill('mailpit');
  await root.getByLabel('Порт').fill('1025');
  await root.getByLabel('Адрес отправителя').fill('estimator@test.estimator.local');
  await next(root);

  await expect(steps.getByRole('button', { name: /Способ входа/ })).toHaveAttribute('aria-current', 'step');
  await root.getByRole('radio', { name: 'Через Active Directory' }).check();
  await root.getByRole('textbox', { name: 'Контроллер 1' }).fill(CONTROLLER);
  await root.locator('input[type="file"]').setInputFiles(CA);
  await expect(root.getByText('✓ сертификат загружен')).toBeVisible();
  await root.getByLabel('Base DN').fill(BASE_DN);
  await root.getByLabel('Сервисная учётка').fill(BIND_DN);
  await root.getByRole('textbox', { name: 'Пароль сервисной учётки' }).fill(AD_PASSWORD);
  await root.getByRole('textbox', { name: 'Группа доступа 1' }).fill(ACCESS);
  await expect(root.getByRole('button', { name: 'Сохранить и продолжить' })).toBeDisabled();

  await root.getByRole('button', { name: 'Проверить подключение' }).click();
  await expect(root.getByRole('status').filter({ hasText: /^✓/ }).first()).toBeVisible();
  await root.getByRole('textbox', { name: 'Логин AD' }).fill(expert.login);
  await root.getByRole('textbox', { name: 'Пароль', exact: true }).fill(expert.password);
  await root.getByRole('button', { name: 'Проверить вход' }).click();
  const result = root.getByRole('status').filter({ hasText: 'Пользователь найден:' });
  await expect(result).toContainText('Expert One');
  await expect(result).toContainText('Учётка активна, пароль верный');
  await expect(result).toContainText('est-access');
  await next(root);

  await expect(steps.getByRole('button', { name: /Политики безопасности/ })).toHaveAttribute('aria-current', 'step');
  await next(root);
  await expect(steps.getByRole('button', { name: /Первый администратор/ })).toHaveAttribute('aria-current', 'step');
});

test('мастер: первый администратор из каталога AD, «Завершить настройку»', async () => {
  await expect(root.getByText(/Найдите учётку AD будущего администратора/)).toBeVisible();
  await root.getByLabel('Найти в AD').fill('moderator');
  const found = root
    .getByRole('list', { name: 'Учётки каталога' })
    .getByRole('listitem')
    .filter({ hasText: 'Moderator One' });
  await found.getByRole('button', { name: 'Выбрать' }).click();
  await expect(root.getByText(admin.login)).toBeVisible();
  await root.getByRole('button', { name: 'Создать…' }).click();
  await stepUp(root, sa);
  await expect(root.getByText('Учётка создана')).toBeVisible();
  await root.getByRole('button', { name: 'Закрыть' }).click();
  await expect(root.getByText('Moderator One')).toBeVisible();

  await root.getByRole('button', { name: 'Завершить настройку' }).click();
  await expect(root.getByRole('heading', { name: 'Приложение готово' })).toBeVisible();
  await root.getByRole('button', { name: 'Перейти в раздел «Система»' }).click();
  await root.goto('/system/auth');
  await expect(root.getByText('Сейчас: через Active Directory')).toBeVisible();
  await expect(root.getByRole('button', { name: 'Перейти на Active Directory…' })).toHaveCount(0);
});

test('администратор из AD: вход паролем каталога и обязательное подключение TOTP', async ({ browser }) => {
  const page = await newPage(browser);
  await signIn(page, admin.login, admin.password, 'Учётная запись компании');
  await enrollTotp(page, admin);
  await expect(page).toHaveURL('/');
  await expect(page.getByRole('link', { name: 'Админка' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Меню пользователя' })).toContainText('Moderator');
});

test('пользователь из группы доступа появляется при первом входе через AD', async ({ browser }) => {
  const page = await newPage(browser);
  await signIn(page, expert.login, 'неверный-пароль', 'Учётная запись компании');
  await expect(page.getByRole('alert')).toBeVisible();
  await expect(page).toHaveURL(/\/login/);

  await page.getByLabel('Пароль').fill(expert.password);
  await spendLogin(1);
  await page.getByRole('button', { name: 'Войти' }).click();
  await expect(page).toHaveURL('/');
  await expect(page.getByRole('button', { name: 'Меню пользователя' })).toContainText('Expert');
  await expect(page.getByRole('link', { name: 'Админка' })).toHaveCount(0);
});

test('суперадминистратор в режиме AD входит паролем приложения и кодом TOTP (FR-SA-03)', async ({ browser }) => {
  const page = await newPage(browser);
  await signIn(page, sa.login, sa.password, 'Учётная запись компании');
  await page.getByLabel('Цифра 1').pressSequentially(await nextCode(page, sa));
  await expect(page).not.toHaveURL(/\/login/);
  await page.goto('/system/auth');
  await expect(page.getByText('Сейчас: через Active Directory')).toBeVisible();
});
