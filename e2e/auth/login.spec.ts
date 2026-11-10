/**
 * FE-090 · вход на настоящем API (SPEC 7.2–7.4, 11.1, TC-AUTH-04): вход local без TOTP и выход,
 * принудительное подключение TOTP, вход с кодом, вход по резервному коду, неверный пароль.
 * Сценарии идут по порядку: подключение TOTP даёт секрет и резервные коды следующим шагам.
 */
import { readFileSync } from 'node:fs';
import { expect, test, type Page } from '@playwright/test';

import { DATA_FILE } from '../global-setup';
import { STEP_SECONDS, currentStep, totp } from './totp';
import { spendLogin } from './budget';

interface Seed {
  user: string;
  admin: string;
  password: string;
}

const seed = JSON.parse(readFileSync(DATA_FILE, 'utf8')) as Seed;

/** Состояние администратора между сценариями: секрет, резервные коды, последний принятый шаг. */
const admin = { secret: '', backup: [] as string[], lastStep: 0 };

test.describe.configure({ mode: 'serial' });

/** CL-14: стили Mantine идут через nonce — нарушений CSP в консоли быть не должно. */
const cspErrors: string[] = [];
test.beforeEach(({ page }) => {
  cspErrors.length = 0;
  page.on('console', (message) => {
    if (message.type() === 'error' && /Content Security Policy/i.test(message.text())) cspErrors.push(message.text());
  });
});
test.afterEach(() => {
  expect(cspErrors).toEqual([]);
});

/** Код следующего шага: сервер не принимает шаг, не больший уже принятого (защита от повтора). */
async function nextCode(page: Page): Promise<string> {
  let step = Math.max(currentStep(), admin.lastStep + 1);
  // окно сервера ±1 шаг: дальше текущего+1 — ждём
  while (step > currentStep() + 1) await page.waitForTimeout(1000);
  step = Math.max(step, currentStep() - 1);
  admin.lastStep = step;
  return totp(admin.secret, step);
}

async function enterCode(page: Page, code: string): Promise<void> {
  await page.getByLabel('Цифра 1').pressSequentially(code);
}

async function signIn(page: Page, login: string, password = seed.password): Promise<void> {
  await page.goto('/login');
  await expect(page.getByRole('heading', { name: 'Вход' })).toBeVisible();
  await expect(page.getByText('Учётная запись приложения')).toBeVisible();
  await page.getByLabel('Логин').fill(login);
  await page.getByLabel('Пароль').fill(password);
  await spendLogin();
  await page.getByRole('button', { name: 'Войти' }).click();
}

async function signOut(page: Page): Promise<void> {
  await page.getByRole('button', { name: 'Меню пользователя' }).click();
  await page.getByRole('menuitem', { name: 'Выйти' }).click();
  await expect(page).toHaveURL(/\/login/);
}

test('неверный пароль: текст ошибки, пароль очищен, логин остался (11.1 №4)', async ({ page }) => {
  await signIn(page, seed.user, 'wrong-password-123');
  await expect(page.getByRole('alert')).toHaveText('Неверный логин или пароль');
  await expect(page.getByLabel('Пароль')).toHaveValue('');
  await expect(page.getByLabel('Логин')).toHaveValue(seed.user);
});

test('вход без TOTP и выход: после выхода приватные страницы ведут на вход', async ({ page }) => {
  await signIn(page, seed.user);
  await expect(page).toHaveURL('/');
  await expect(page.getByRole('navigation', { name: 'Разделы' })).toBeVisible();
  await signOut(page);
  await page.goto('/profile');
  await expect(page).toHaveURL(/\/login\?next=%2Fprofile/);
});

test('профиль на настоящем API: сессии, письма, ФИО (FR-SESS-04, FR-NOTIF-02)', async ({ page }) => {
  await signIn(page, seed.user);
  await expect(page).toHaveURL('/');
  await page.goto('/profile');
  await expect(page.getByRole('heading', { name: 'Профиль', level: 1 })).toBeVisible();

  const sessions = page.getByRole('region', { name: 'Активные сессии' });
  await expect(sessions.getByText('текущая')).toBeVisible();

  const digest = page.getByRole('region', { name: 'Письма' }).getByLabel('Ежедневная сводка');
  const before = await digest.isChecked();
  const saved = page.waitForResponse((r) => r.url().endsWith('/me/notification-settings') && r.request().method() === 'PUT');
  // у Switch Mantine input скрыт: кликаем по подписи
  await page.getByRole('region', { name: 'Письма' }).getByText('Ежедневная сводка').click();
  expect((await saved).status()).toBe(200);
  await page.reload();
  await expect(page.getByRole('region', { name: 'Письма' }).getByLabel('Ежедневная сводка')).toBeChecked({ checked: !before });

  const account = page.getByRole('region', { name: 'Учётная запись' });
  await account.getByLabel('ФИО').fill('Тестов Пользователь Е2Е');
  await account.getByRole('button', { name: 'Сохранить' }).click();
  await expect(page.getByRole('button', { name: 'Меню пользователя' })).toContainText('Тестов П.');
  await signOut(page);
});

test('принудительное подключение TOTP: только этот экран, затем резервные коды (FR-2FA-04)', async ({
  page,
}) => {
  await signIn(page, seed.admin);
  await expect(page).toHaveURL('/enroll-totp');
  await expect(page.getByRole('heading', { name: 'Подключите вход по коду' })).toBeVisible();
  await expect(page.getByRole('img', { name: 'QR-код для приложения-аутентификатора' })).toBeVisible();
  admin.secret = (await page.getByLabel('Секрет').textContent())?.trim() ?? '';
  expect(admin.secret).toMatch(/^[A-Z2-7]{16,}$/);

  // до подключения другие страницы недоступны
  await page.goto('/profile');
  await expect(page).toHaveURL('/enroll-totp');
  admin.secret = (await page.getByLabel('Секрет').textContent())?.trim() ?? admin.secret;

  await enterCode(page, await nextCode(page));
  const codes = page.getByLabel('Резервные коды').locator('span');
  await expect(codes).toHaveCount(10);
  admin.backup = await codes.allTextContents();
  expect(admin.backup.every((c) => /^\d{8}$/.test(c))).toBe(true);

  await page.getByRole('button', { name: 'Продолжить' }).click();
  await expect(page).toHaveURL('/');
  await expect(page.getByRole('link', { name: 'Админка' })).toBeVisible();
  await signOut(page);
});

test('вход с кодом TOTP (11.1 №6)', async ({ page }) => {
  test.skip(!admin.secret, 'нужен секрет из сценария подключения');
  await signIn(page, seed.admin);
  await expect(page.getByRole('heading', { name: 'Подтвердите вход' })).toBeVisible();
  await enterCode(page, await nextCode(page));
  await expect(page).toHaveURL('/');
  await signOut(page);
});

test('вход по резервному коду; повторно тот же код не принимается (11.1 №7)', async ({ page }) => {
  test.skip(admin.backup.length === 0, 'нужны резервные коды из сценария подключения');
  const [code = ''] = admin.backup;
  await signIn(page, seed.admin);
  await page.getByRole('button', { name: 'Использовать резервный код' }).click();
  await page.getByLabel('Резервный код').fill(code);
  await page.getByRole('button', { name: 'Подтвердить' }).click();
  await expect(page).toHaveURL('/');
  await signOut(page);

  await signIn(page, seed.admin);
  await page.getByRole('button', { name: 'Использовать резервный код' }).click();
  await page.getByLabel('Резервный код').fill(code);
  await page.getByRole('button', { name: 'Подтвердить' }).click();
  await expect(page.getByRole('alert')).toBeVisible();
  await expect(page).toHaveURL(/\/login/);
});

test.afterAll(() => {
  // время шага в отчёте помогает разбирать отказы TOTP
  console.log(`TOTP: последний шаг ${admin.lastStep}, длина шага ${STEP_SECONDS} с`);
});
