/** FE-065 · журнал аудита: категории по ролям, фильтры, детали, выгрузка CSV со step-up. */
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { NOW } from '../../shared/api/mocks/ids';
import { PERSONAS } from '../../shared/api/mocks/personas';
import { persona } from '../../test/setup';
import { renderApp } from '../../test/render';
import { defaultFilters, eventOptions, periodValid, queryOf, visibleCategories } from './audit';

async function open(who: 'auditor' | 'admin' | 'superadmin', path = '/audit') {
  persona.current = who === 'auditor' ? PERSONAS.auditor : who === 'admin' ? PERSONAS.admin : PERSONAS.superadmin;
  renderApp(path);
  await screen.findByRole('table');
  return () => within(screen.getByRole('table'));
}

async function stepUp() {
  const dialog = await screen.findByRole('dialog', { name: 'Подтвердите действие' });
  fireEvent.change(within(dialog).getByLabelText('Пароль', { selector: 'input' }), { target: { value: 'pw' } });
  fireEvent.paste(within(dialog).getByLabelText('Цифра 1'), { clipboardData: { getData: () => '123456' } });
}

describe('правила журнала', () => {
  it('администратор видит две категории, аудитор — все', () => {
    expect(visibleCategories(['admin'])).toEqual(['users_roles', 'dictionaries']);
    expect(visibleCategories(['security_auditor'])).toHaveLength(7);
    expect(eventOptions(['admin']).map((g) => g.group)).toEqual(['Пользователи и роли', 'Справочники']);
    expect(eventOptions(['admin'])[0]?.items.some((i) => i.value === 'users.blocked')).toBe(true);
  });

  it('период по умолчанию — 7 дней; пустые фильтры не уходят в запрос', () => {
    const f = defaultFilters(new Date(2026, 10, 9, 12));
    expect([f.from, f.to]).toEqual(['2026-11-03', '2026-11-09']);
    expect(periodValid(f)).toBe(true);
    expect(periodValid({ ...f, from: '2026-11-10' })).toBe(false);
    const q = queryOf({ ...f, result: 'denied' });
    expect(Object.keys(q)).toEqual(['from', 'to', 'result']);
  });
});

describe('экран «Журнал аудита»', () => {
  // демо-записи журнала — до NOW моков, а период по умолчанию (7 дней) считается от «сегодня»:
  // часы теста начинаются с NOW и дальше идут как обычно
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['Date'], shouldAdvanceTime: true });
    vi.setSystemTime(new Date(NOW));
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('аудитор ИБ: события всех категорий, фильтр результата, детали записи', async () => {
    const table = await open('auditor');
    expect(table().getAllByText('Неуспешный вход').length).toBe(2);
    expect(table().getAllByText('Справочники').length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole('textbox', { name: 'Результат' }));
    fireEvent.click(await screen.findByRole('option', { name: 'Отказ' }));
    fireEvent.click(screen.getByRole('button', { name: 'Применить' }));
    await waitFor(() => expect(table().queryByText('Успех')).toBeNull());
    expect(table().getAllByText('Отказ').length).toBeGreaterThan(0);
    fireEvent.click(table().getByRole('button', { name: /^Отказ в доступе/ }));
    const details = await screen.findByRole('complementary', { name: 'Запись журнала' });
    expect(within(details).getByText(/money\.read/)).toBeTruthy();
    expect(within(details).getByText(/факт изменения без значений/)).toBeTruthy();
  });

  it('администратор: только «Пользователи и роли» и «Справочники», без выгрузки', async () => {
    const table = await open('admin');
    expect(screen.getByText(/Вам видны только события категорий/)).toBeTruthy();
    const cats = table()
      .getAllByRole('row')
      .slice(1)
      .map((r) => r.querySelectorAll('td')[2]?.textContent);
    expect(new Set(cats)).toEqual(new Set(['Пользователи и роли', 'Справочники']));
    expect(screen.queryByRole('button', { name: /Выгрузить CSV/ })).toBeNull();
  });

  it('суперадминистратор: журнал в разделе «Система», выгрузка CSV со step-up', async () => {
    const created = vi.fn(() => 'blob:x');
    Object.assign(URL, { createObjectURL: created, revokeObjectURL: vi.fn() });
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined);
    await open('superadmin');
    expect(screen.getByRole('navigation', { name: 'Разделы системы' })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: /Выгрузить CSV/ }));
    await stepUp();
    await waitFor(() => expect(created).toHaveBeenCalled(), { timeout: 5000 });
    expect(click).toHaveBeenCalled();
    click.mockRestore();
  });

  it('«Показать ещё» подгружает следующую страницу', async () => {
    const table = await open('auditor');
    fireEvent.change(screen.getByLabelText('С'), { target: { value: '2026-10-01' } });
    fireEvent.click(screen.getByRole('button', { name: 'Применить' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Показать ещё' }));
    await waitFor(() => expect(table().getAllByRole('row').length).toBeGreaterThan(51));
  });
});
