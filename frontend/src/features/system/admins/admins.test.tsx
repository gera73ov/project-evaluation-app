/** FE-063 · учётки раздела «Система», анонимизация и реестр проектов. */
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { PERSONAS } from '../../../shared/api/mocks/personas';
import { persona } from '../../../test/setup';
import { renderApp } from '../../../test/render';
import { accountsOf, isLastSuperadmin } from './accounts';

const acc = (id: string, roles: string[], status = 'active', full_name = id) =>
  ({ id, roles, status, full_name }) as never;

async function open(path: string, ready: string) {
  persona.current = PERSONAS.superadmin;
  renderApp(path);
  await screen.findByText(ready);
  return screen.getByRole('table');
}

async function stepUp() {
  const dialog = await screen.findByRole('dialog', { name: 'Подтвердите действие' });
  fireEvent.change(within(dialog).getByLabelText('Пароль', { selector: 'input' }), { target: { value: 'pw' } });
  fireEvent.paste(within(dialog).getByLabelText('Цифра 1'), { clipboardData: { getData: () => '123456' } });
}

async function confirm(name: RegExp, button: string) {
  const dialog = await screen.findByRole('dialog', { name });
  fireEvent.click(within(dialog).getByRole('button', { name: button }));
}

describe('правила учёток', () => {
  it('пункты меню и последний суперадминистратор', () => {
    const items = [acc('b', ['admin']), acc('a', ['superadmin']), acc('c', ['security_auditor'])];
    expect(accountsOf(items, 'admins').map((a: { id: string }) => a.id)).toEqual(['a', 'b']);
    expect(accountsOf(items, 'auditors').map((a: { id: string }) => a.id)).toEqual(['c']);
    expect(isLastSuperadmin(items[1] as never, items)).toBe(true);
    expect(isLastSuperadmin(items[1] as never, [...items, acc('d', ['superadmin'])])).toBe(false);
    expect(isLastSuperadmin(items[1] as never, [...items, acc('d', ['superadmin'], 'blocked')])).toBe(true);
  });
});

describe('«Суперадминистраторы и администраторы»', () => {
  it('список без аудиторов; блокировка со step-up', async () => {
    const table = await open('/system/admins', PERSONAS.admin.fullName);
    expect(within(table).queryByText('Аудитор ИБ')).toBeNull();
    fireEvent.click(within(table).getByRole('button', { name: PERSONAS.admin.fullName }));
    fireEvent.click(screen.getByRole('button', { name: 'Заблокировать' }));
    await confirm(/^Заблокировать/, 'Заблокировать');
    await stepUp();
    expect(await screen.findByText('✓ Учётка заблокирована')).toBeTruthy();
    await waitFor(() => expect(screen.getByRole('button', { name: 'Разблокировать' })).toBeTruthy());
  });

  it('последнего суперадминистратора нельзя заблокировать и разжаловать', async () => {
    const table = await open('/system/admins', 'С. Петрова');
    fireEvent.click(within(table).getByRole('button', { name: 'С. Петрова' }));
    fireEvent.click(screen.getByRole('button', { name: 'Разжаловать' }));
    await confirm(/^Разжаловать/, 'Разжаловать');
    await stepUp();
    expect(await screen.findByText('✓ Роль снята')).toBeTruthy();
    await waitFor(() => expect(within(screen.getByRole('table')).queryByText('С. Петрова')).toBeNull());
    fireEvent.click(within(screen.getByRole('table')).getByRole('button', { name: PERSONAS.superadmin.fullName }));
    expect((screen.getByRole('button', { name: 'Заблокировать' }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole('button', { name: 'Разжаловать' }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(/последний активный суперадминистратор/)).toBeTruthy();
  });

  it('создание суперадминистратора: письмо со ссылкой; четвёртого создать нельзя', async () => {
    const table = await open('/system/admins', 'С. Петрова');
    fireEvent.click(screen.getByRole('button', { name: '+ Добавить' }));
    const create = screen.getByRole('button', { name: 'Создать…' }) as HTMLButtonElement;
    expect(create.disabled).toBe(true);
    fireEvent.change(screen.getByLabelText(/Логин/), { target: { value: 'sa.orlov' } });
    fireEvent.change(screen.getByLabelText(/ФИО/), { target: { value: 'К. Орлов' } });
    fireEvent.change(screen.getByLabelText(/Email/), { target: { value: 'sa.orlov@corp.local' } });
    fireEvent.click(screen.getByRole('radio', { name: 'Суперадминистратор' }));
    expect(screen.getByText(/оповестит всех администраторов и ИБ/)).toBeTruthy();
    fireEvent.click(create);
    await stepUp();
    expect(await screen.findByText('Учётка создана')).toBeTruthy();
    expect(screen.getByText(/Ссылка активации отправлена письмом/)).toBeTruthy();
    await waitFor(() => expect(within(table).getByText('К. Орлов')).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: 'Закрыть' }));
    fireEvent.click(screen.getByRole('button', { name: '+ Добавить' }));
    expect((screen.getByRole('radio', { name: 'Суперадминистратор' }) as HTMLInputElement).disabled).toBe(true);
    expect(screen.getByText(/Суперадминистраторов уже три/)).toBeTruthy();
  });

  it('«Аудиторы ИБ» — только аудиторы, роль при создании не выбирается', async () => {
    const table = await open('/system/auditors', PERSONAS.auditor.fullName);
    expect(within(table).getByText(PERSONAS.auditor.fullName)).toBeTruthy();
    expect(within(table).queryByText('Суперадминистратор')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: '+ Добавить' }));
    expect(screen.getByText('Новый аудитор ИБ')).toBeTruthy();
    expect(screen.queryByRole('radio')).toBeNull();
  });
});

describe('«Анонимизация» и «Реестр проектов»', () => {
  it('только заблокированные; необратимо, со step-up', async () => {
    const table = await open('/system/anonymize', 'В. Блинов');
    expect(within(table).getAllByRole('row')).toHaveLength(2);
    fireEvent.click(within(table).getByRole('button', { name: 'Анонимизировать В. Блинов' }));
    await confirm(/^Анонимизировать В\. Блинов/, 'Анонимизировать…');
    await stepUp();
    expect(await screen.findByText('✓ В. Блинов анонимизирован(а)')).toBeTruthy();
    expect(await screen.findByText('Заблокированных учёток нет')).toBeTruthy();
  });

  it('реестр без денег, «без модератора N дней»', async () => {
    const table = await open('/system/projects', 'Портал дилеров');
    expect(within(table).getByText('Портал дилеров')).toBeTruthy();
    expect(within(table).getByText('без модератора 12 дней')).toBeTruthy();
    expect(document.body.textContent).not.toMatch(/₽|USD/);
  });
});
