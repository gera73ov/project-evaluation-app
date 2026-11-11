/** FE-064 · мастер первичной настройки: обе ветки, продолжение с прерванного шага. */
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { postStep, restartDemoSetup } from '../../shared/api/mocks/demoSetup';
import { PERSONAS } from '../../shared/api/mocks/personas';
import { persona } from '../../test/setup';
import { renderApp } from '../../test/render';
import { currentStep, isHttpsUrl, reachable, withDefaults, type SetupStep } from './setup';

const NEXT = 'Сохранить и продолжить';
const button = (name: string | RegExp) => screen.getByRole('button', { name }) as HTMLButtonElement;
const step = (s: SetupStep['step'], done: boolean): SetupStep => ({ step: s, done });

async function stepUp() {
  const dialog = await screen.findByRole('dialog', { name: 'Подтвердите действие' });
  fireEvent.change(within(dialog).getByLabelText('Пароль', { selector: 'input' }), { target: { value: 'pw' } });
  fireEvent.paste(within(dialog).getByLabelText('Цифра 1'), { clipboardData: { getData: () => '123456' } });
}

const heading = (name: string) => screen.findByRole('heading', { name });

async function passAddressAndMail() {
  await heading('Адрес и часовой пояс');
  fireEvent.click(button(NEXT));
  expect(await screen.findByText('Нужен адрес https://…')).toBeTruthy();
  fireEvent.change(screen.getByLabelText('Адрес приложения'), { target: { value: 'https://estimator.corp.local' } });
  fireEvent.click(button(NEXT));
  await heading('Почта');
  expect((screen.getByLabelText('Сервер') as HTMLInputElement).value).toBe('mail.corp.local');
  fireEvent.click(button(NEXT));
  await heading('Как входят пользователи');
}

describe('правила мастера', () => {
  it('текущий шаг — первый незавершённый; будущие закрыты', () => {
    const steps = [step('app', true), step('smtp', false), step('auth', false)];
    expect(currentStep(steps)).toBe('smtp');
    expect(reachable('app', steps)).toBe(true);
    expect(reachable('auth', steps)).toBe(false);
    const all = (['app', 'smtp', 'auth', 'security', 'first_admin'] as const).map((s) => step(s, true));
    expect(currentStep(all)).toBeNull();
  });

  it('адрес только https, значения по умолчанию из схемы', () => {
    expect(isHttpsUrl('https://estimator.corp.local')).toBe(true);
    expect(isHttpsUrl('http://estimator.corp.local')).toBe(false);
    expect(isHttpsUrl('https://')).toBe(false);
    expect(withDefaults('app', {})).toEqual({ 'app.base_url': null, 'app.timezone': 'Europe/Moscow' });
  });
});

describe('мастер первичной настройки', () => {
  it('пройденный мастер: раздел «Система» открывается сразу, /setup — «Приложение готово»', async () => {
    persona.current = PERSONAS.superadmin;
    renderApp('/setup');
    expect(await heading('Приложение готово')).toBeTruthy();
  });

  it('ветка «Приложение»: пять шагов, первый администратор, «Приложение готово»', async () => {
    restartDemoSetup();
    persona.current = PERSONAS.superadmin;
    renderApp('/system');
    await passAddressAndMail();
    expect((screen.getByRole('radio', { name: /Через приложение/ }) as HTMLInputElement).checked).toBe(true);
    expect(screen.getByRole('group', { name: /^Пароли/ })).toBeTruthy();
    fireEvent.click(button(NEXT));
    await heading('Политики безопасности');
    expect(screen.queryByRole('group', { name: /^Пароли/ })).toBeNull();
    fireEvent.click(button(NEXT));

    await heading('Первый администратор');
    expect(button('Завершить настройку').disabled).toBe(true);
    expect(screen.queryByRole('radio')).toBeNull();
    fireEvent.change(await screen.findByLabelText(/Логин/), { target: { value: 'a.smirnov' } });
    fireEvent.change(screen.getByLabelText(/ФИО/), { target: { value: 'А. Смирнов' } });
    fireEvent.change(screen.getByLabelText(/Email/), { target: { value: 'a.smirnov@corp.local' } });
    fireEvent.click(button('Создать…'));
    await stepUp();
    expect(await screen.findByText('Учётка создана')).toBeTruthy();
    await waitFor(() => expect(button('Завершить настройку').disabled).toBe(false));
    expect(screen.getByText('А. Смирнов')).toBeTruthy();
    fireEvent.click(button('Завершить настройку'));
    expect(await heading('Приложение готово')).toBeTruthy();
    expect(screen.getAllByText('✓')).toHaveLength(5);
  });

  it('ветка AD: сохранить шаг можно только после обеих проверок', async () => {
    restartDemoSetup();
    persona.current = PERSONAS.superadmin;
    renderApp('/setup');
    await passAddressAndMail();
    fireEvent.click(screen.getByRole('radio', { name: /Active Directory/ }));
    await heading('Подключение');
    expect(button(NEXT).disabled).toBe(true);
    fireEvent.change(screen.getByLabelText('Пароль сервисной учётки'), { target: { value: 'svc-secret' } });
    fireEvent.click(button('Проверить подключение'));
    expect(await screen.findByText(/Подключено к dc1\.corp\.local/)).toBeTruthy();
    fireEvent.change(screen.getByLabelText('Логин AD'), { target: { value: 'i.ivanov' } });
    fireEvent.change(screen.getByLabelText('Пароль', { selector: 'input' }), { target: { value: 'secret' } });
    fireEvent.click(button('Проверить вход'));
    await screen.findByText(/Пользователь найден/);
    await waitFor(() => expect(button(NEXT).disabled).toBe(false));
    fireEvent.click(button(NEXT));
    await heading('Политики безопасности');
    fireEvent.click(button(NEXT));
    await heading('Первый администратор');
    expect(screen.getByText(/Найдите учётку AD будущего администратора/)).toBeTruthy();
    // CR-011: поиск по каталогу из раздела «Система», учётка без группы доступа не выбирается
    expect(screen.queryByLabelText(/^Логин/)).toBeNull();
    fireEvent.change(await screen.findByLabelText(/Найти в AD/), { target: { value: 'волк' } });
    const list = await screen.findByRole('list', { name: 'Учётки каталога' });
    const row = within(list).getByText('Волкова Анна Сергеевна').closest('li') as HTMLElement;
    fireEvent.click(within(row).getByRole('button', { name: 'Выбрать' }));
    expect(screen.getByText(/a\.volkova · a\.volkova@corp\.ru/)).toBeTruthy();
    fireEvent.click(button('Создать…'));
    await stepUp();
    expect(await screen.findByText('Учётка создана')).toBeTruthy();
    await waitFor(() => expect(button('Завершить настройку').disabled).toBe(false));
    expect(screen.getByText('Волкова Анна Сергеевна')).toBeTruthy();
  });

  it('прерванная настройка продолжается с того же шага, пройденный шаг можно открыть', async () => {
    restartDemoSetup();
    postStep('app', { values: { 'app.base_url': 'https://e.corp.local' } });
    postStep('smtp', { values: {} });
    persona.current = PERSONAS.superadmin;
    renderApp('/system/security');
    expect(await heading('Как входят пользователи')).toBeTruthy();
    expect(button(/Политики безопасности/).disabled).toBe(true);
    fireEvent.click(button(/Адрес и часовой пояс/));
    await heading('Адрес и часовой пояс');
    expect((screen.getByLabelText('Адрес приложения') as HTMLInputElement).value).toBe('https://e.corp.local');
    expect(button('Сохранить')).toBeTruthy();
  });
});
