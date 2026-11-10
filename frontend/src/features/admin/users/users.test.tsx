/** FE-070 · «Пользователи»: список и форма, «Найти в AD», блокировка и сбросы, «Заменить участника». */
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { setSetting } from '../../../shared/api/mocks/demoSystem';
import { PEOPLE } from '../../../shared/api/mocks/data';
import { PERSONAS } from '../../../shared/api/mocks/personas';
import { persona } from '../../../test/setup';
import { renderApp } from '../../../test/render';
import { mappedByGroups, replacementCandidates, roleLocked, type User } from './users';

const u = (patch: Partial<User>): User => ({
  id: 'u',
  login: 'u',
  full_name: 'U',
  email: null,
  source: 'local',
  system_roles: [],
  status: 'active',
  block_reason: null,
  last_login_at: null,
  totp_enabled: true,
  ...patch,
});

async function open() {
  persona.current = PERSONAS.admin;
  renderApp('/admin');
  await screen.findByRole('table');
  return () => within(screen.getByRole('table'));
}

const button = (name: string | RegExp) => screen.getByRole('button', { name }) as HTMLButtonElement;

async function stepUp() {
  const dialog = await screen.findByRole('dialog', { name: 'Подтвердите действие' });
  fireEvent.change(within(dialog).getByLabelText('Пароль', { selector: 'input' }), { target: { value: 'pw' } });
  fireEvent.paste(within(dialog).getByLabelText('Цифра 1'), { clipboardData: { getData: () => '123456' } });
}

describe('правила экрана «Пользователи»', () => {
  it('роли из групп AD и свои роли не меняются; замена — активный и не сам', () => {
    const ad = u({ source: 'ad', system_roles: [{ role: 'moderator', source: 'ad_group' }] });
    expect(mappedByGroups(ad)).toBe(true);
    expect(roleLocked(ad, 'moderator', false)).toBe(true);
    expect(roleLocked(ad, 'presale_head', false)).toBe(false);
    expect(roleLocked(u({}), 'moderator', true)).toBe(true);
    const list = [u({ id: 'a' }), u({ id: 'b', status: 'blocked' }), u({ id: 'c' })];
    expect(replacementCandidates(list, list[0]!).map((x) => x.id)).toEqual(['c']);
  });
});

describe('экран «Пользователи»', () => {
  it('поиск, роли и блокировка; себя заблокировать нельзя', async () => {
    const table = await open();
    expect(table().getByText('Т. Лебедева')).toBeTruthy();
    expect(table().queryByText('Суперадминистратор')).toBeNull();
    fireEvent.change(screen.getByLabelText('ФИО или логин'), { target: { value: 'козлов' } });
    await waitFor(() => expect(table().queryByText('Т. Лебедева')).toBeNull());
    fireEvent.click(table().getByRole('button', { name: PERSONAS.admin.fullName }));
    expect(button('Заблокировать').disabled).toBe(true);
    expect(screen.getByText(/Свои роли менять/)).toBeTruthy();

    fireEvent.change(screen.getByLabelText('ФИО или логин'), { target: { value: '' } });
    fireEvent.click(await screen.findByRole('button', { name: PEOPLE.petrov.fullName }));
    fireEvent.click(screen.getByRole('checkbox', { name: 'Пресейл' }));
    fireEvent.click(button('Сохранить роли'));
    expect(await screen.findByText('✓ Роли сохранены')).toBeTruthy();
    await waitFor(() => expect(table().getAllByText('Пресейл').length).toBeGreaterThan(1));

    fireEvent.click(button('Заблокировать'));
    const dialog = await screen.findByRole('dialog', { name: /^Заблокировать/ });
    fireEvent.change(within(dialog).getByLabelText(/Причина/), { target: { value: 'Уволился' } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Заблокировать' }));
    expect(await screen.findByText('✓ Пользователь заблокирован')).toBeTruthy();
    expect(await screen.findByRole('button', { name: 'Разблокировать' })).toBeTruthy();
  });

  it('создание в режиме «Приложение»; без email ссылка — на экране после сброса со step-up', async () => {
    const table = await open();
    fireEvent.click(button('+ Добавить'));
    fireEvent.change(screen.getByLabelText(/Логин/), { target: { value: 'z.zaitsev' } });
    fireEvent.change(screen.getByRole('textbox', { name: /^ФИО\s*\*?$/ }), { target: { value: 'З. Зайцев' } });
    fireEvent.click(screen.getByRole('checkbox', { name: 'Модератор' }));
    fireEvent.click(button('Создать'));
    expect(await screen.findByText('Пользователь создан')).toBeTruthy();
    expect(screen.getByText(/передайте ссылку лично/)).toBeTruthy();
    await waitFor(() => expect(table().getByText('З. Зайцев')).toBeTruthy());

    fireEvent.click(table().getByRole('button', { name: PEOPLE.kuznetsova.fullName }));
    fireEvent.click(button('Сбросить пароль'));
    const confirm = await screen.findByRole('dialog', { name: /^Сбросить пароль/ });
    fireEvent.click(within(confirm).getByRole('button', { name: 'Сбросить пароль' }));
    await stepUp();
    expect(await screen.findByText('✓ Пароль сброшен')).toBeTruthy();
    expect(screen.getByText(/https:\/\/estimator\.corp\.local\/activate/)).toBeTruthy();
  });

  it('режим AD: «Найти в AD» — вне группы доступа не завести, заведённого открыть', async () => {
    setSetting('auth.mode', 'ad');
    await open();
    fireEvent.click(button('+ Добавить'));
    fireEvent.change(screen.getByLabelText('Найти в AD'), { target: { value: 'вол' } });
    const results = await screen.findByRole('list', { name: 'Учётки каталога' });
    expect(within(results).getAllByRole('listitem')).toHaveLength(2);
    fireEvent.change(screen.getByLabelText('Найти в AD'), { target: { value: 'belova' } });
    expect(await screen.findByText('нет в группе доступа')).toBeTruthy();
    fireEvent.change(screen.getByLabelText('Найти в AD'), { target: { value: 'Волкова' } });
    fireEvent.click(await screen.findByRole('button', { name: 'Выбрать' }));
    fireEvent.click(screen.getByRole('checkbox', { name: 'Пресейл' }));
    fireEvent.click(button('Создать'));
    expect(await screen.findByText(/войти можно паролем AD сразу/)).toBeTruthy();
  });

  it('«Заменить участника» модератора: без нужной роли перенести нельзя; замена — только активные', async () => {
    const table = await open();
    fireEvent.click(table().getByRole('button', { name: PERSONAS.moderator.fullName }));
    fireEvent.click(button('Заменить участника…'));
    const dialog = await screen.findByRole('dialog', { name: /Заменить участника/ });
    fireEvent.click(within(dialog).getByRole('textbox', { name: 'Кем заменить' }));
    fireEvent.click(await screen.findByRole('option', { name: /П\. Петров/ }));
    fireEvent.click(within(dialog).getByRole('button', { name: 'Далее' }));
    expect(await within(dialog).findByText('Портал дилеров')).toBeTruthy();
    expect(within(dialog).getByText(/нет системной роли «Модератор»/)).toBeTruthy();
    expect((within(dialog).getByRole('checkbox', { name: 'Портал дилеров' }) as HTMLInputElement).disabled).toBe(true);
    expect((within(dialog).getByRole('button', { name: 'Заменить…' }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(within(dialog).getByRole('button', { name: 'Назад' }));

    fireEvent.click(within(dialog).getByRole('textbox', { name: 'Кем заменить' }));
    expect(await screen.findByRole('option', { name: /П\. Сидоров/ })).toBeTruthy();
    expect(screen.queryByRole('option', { name: /Т\. Лебедева/ })).toBeNull(); // не активирован
    expect(screen.queryByRole('option', { name: /Н\. Новиков/ })).toBeNull(); // заблокирован
  });

  it('«Заменить участника» эксперта: снятие отметок и итог', async () => {
    const table = await open();
    fireEvent.click(table().getByRole('button', { name: PEOPLE.orlova.fullName }));
    fireEvent.click(button('Заменить участника…'));
    const dialog = await screen.findByRole('dialog', { name: /Заменить участника/ });
    fireEvent.click(within(dialog).getByRole('textbox', { name: 'Кем заменить' }));
    fireEvent.click(await screen.findByRole('option', { name: /П\. Петров/ }));
    fireEvent.click(within(dialog).getByRole('button', { name: 'Далее' }));
    const box = (await within(dialog).findByRole('checkbox', { name: 'Портал дилеров' })) as HTMLInputElement;
    expect(box.checked).toBe(true);
    expect(within(dialog).getByText(/Эксперт · Тестирование|Эксперт/)).toBeTruthy();
    expect(within(dialog).getByText(/2 открытых вопроса/)).toBeTruthy();
    fireEvent.click(within(dialog).getByRole('button', { name: 'Заменить…' }));
    expect(within(dialog).getByText(/в 1 проекте\?/)).toBeTruthy();
    fireEvent.click(within(dialog).getByRole('button', { name: 'Заменить' }));
    expect(await within(dialog).findByText(/заменяет участника в 1 проекте/)).toBeTruthy();
  });
});
