/** FE-061 · «Аутентификация»: подключение к AD, проверки, роли по группам, переход на AD. */
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { PERSONAS } from '../../../shared/api/mocks/personas';
import { persona, server } from '../../../test/setup';
import { renderApp } from '../../../test/render';
import { formOf, parseController, validate, valuesOf } from './auth';
import { unresolved } from './SwitchWizard';

afterEach(() => server.events.removeAllListeners());

function captureBodies(method: string, path: string) {
  const bodies: unknown[] = [];
  server.events.on('request:start', ({ request }) => {
    if (request.method === method && new URL(request.url).pathname === path)
      void request
        .clone()
        .json()
        .then((b) => bodies.push(b));
  });
  return bodies;
}

async function open() {
  persona.current = PERSONAS.superadmin;
  renderApp('/system/auth');
  await screen.findByRole('heading', { name: 'Способ входа' });
}

async function stepUp() {
  const dialog = await screen.findByRole('dialog', { name: 'Подтвердите действие' });
  fireEvent.change(within(dialog).getByLabelText('Пароль', { selector: 'input' }), { target: { value: 'pw' } });
  fireEvent.paste(within(dialog).getByLabelText('Цифра 1'), { clipboardData: { getData: () => '123456' } });
}

const button = (name: string | RegExp) => screen.getByRole('button', { name }) as HTMLButtonElement;

describe('правила формы AD', () => {
  it('контроллер: host:port, без порта — порт протокола', () => {
    expect(parseController('dc1.corp.local:636', 'ldaps')).toEqual({ host: 'dc1.corp.local', port: 636 });
    expect(parseController('dc1', 'starttls')).toEqual({ host: 'dc1', port: 389 });
    expect(parseController('dc1:99999', 'ldaps')).toBeNull();
    expect(parseController('ldap://dc1', 'ldaps')).toBeNull();
  });

  it('обязательные поля и {login} в фильтре', () => {
    const form = formOf({});
    expect(validate(form)).toEqual(['controllers', 'baseDn', 'bindDn', 'bindPassword', 'accessGroups']);
    const ok = {
      ...form,
      controllers: ['dc1:636'],
      baseDn: 'DC=corp',
      bindDn: 'CN=svc',
      bindPassword: 'secret',
      accessGroups: ['CN=Users'],
      userFilter: '(uid=x)',
    };
    expect(validate(ok)).toEqual(['userFilter']);
    expect(validate({ ...ok, userFilter: '(uid={login})', mappingEnabled: true })).toEqual(['mapping']);
  });

  it('значения раздела: пароль только при изменении, группы без пустых и повторов', () => {
    const form = { ...formOf({}), accessGroups: ['CN=A', ' ', 'CN=A'], moderatorGroup: 'CN=M' };
    const values = valuesOf(form);
    expect(values['auth.ad.access_groups']).toEqual(['CN=A']);
    expect(values['auth.ad.role_mapping']).toEqual({
      enabled: false,
      mappings: [{ group_dn: 'CN=M', role: 'moderator' }],
    });
    expect('auth.ad.bind_password' in values).toBe(false);
    expect(valuesOf({ ...form, bindPassword: 'p' })['auth.ad.bind_password']).toBe('p');
  });

  it('нерешённые неоднозначные', () => {
    const c = (id: string) => ({ user_id: id, login: id, full_name: id, ad_candidates: [] });
    const report = { matched: [], ambiguous: [c('a'), c('b')], not_found: [], applied: false };
    expect(unresolved(report, new Map([['a', 'none']]))).toBe(1);
  });
});

describe('экран «Аутентификация»', () => {
  it('режим «Приложение», подсказка про суперадминистраторов, нешифрованного LDAP нет', async () => {
    await open();
    expect(screen.getByText('Сейчас: через приложение')).toBeTruthy();
    expect(screen.getByText(/Суперадминистраторы всегда входят паролем приложения/)).toBeTruthy();
    expect((screen.getByLabelText('Контроллер 1') as HTMLInputElement).value).toBe('dc1.corp.local:636');
    const radios = screen.getAllByRole('radio').map((r) => r.closest('label, div')?.textContent);
    expect(radios.join(' ')).not.toMatch(/\bLDAP\b(?!S)/);
    expect(screen.getByText('Без шифрования недоступно')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'изменить' })).toBeTruthy();
    expect(button('Сохранить…').disabled).toBe(true);
  });

  it('«Сохранить…» — только после обеих проверок с текущими параметрами, затем step-up', async () => {
    const bodies = captureBodies('PUT', '/api/v1/system/settings/auth');
    await open();
    fireEvent.change(screen.getByLabelText('Base DN'), { target: { value: 'OU=Staff,DC=corp,DC=local' } });
    expect(button('Сохранить…').disabled).toBe(true);
    fireEvent.click(button('Проверить подключение'));
    expect(await screen.findByText('✓ Подключено к dc1.corp.local за 0,2 с')).toBeTruthy();
    expect(button('Сохранить…').disabled).toBe(true);

    fireEvent.change(screen.getByLabelText('Логин AD'), { target: { value: 'i.ivanov' } });
    fireEvent.change(screen.getByLabelText('Пароль', { selector: 'input' }), { target: { value: 'secret' } });
    fireEvent.click(button('Проверить вход'));
    const result = await screen.findByText(/Пользователь найден/);
    expect(result.closest('.auth-result')?.textContent).toContain('Иванов Иван Иванович, i.ivanov@corp.ru');
    expect(screen.getByText(/APP-Estimator-Users, APP-Estimator-Moderators/)).toBeTruthy();
    await waitFor(() => expect(button('Сохранить…').disabled).toBe(false));

    // любое изменение после проверок снова требует их
    fireEvent.change(screen.getByLabelText('Base DN'), { target: { value: 'OU=Staff2,DC=corp,DC=local' } });
    expect(button('Сохранить…').disabled).toBe(true);
    fireEvent.change(screen.getByLabelText('Base DN'), { target: { value: 'OU=Staff,DC=corp,DC=local' } });
    expect(button('Сохранить…').disabled).toBe(false);

    fireEvent.click(button('Сохранить…'));
    await stepUp();
    expect(await screen.findByText('✓ Настройки AD сохранены')).toBeTruthy();
    expect(bodies).toHaveLength(2); // без подтверждения → 403, после — повтор
    const values = (bodies[1] as { values: Record<string, { base_dn: string }> }).values;
    expect(values['auth.ad.connection']?.base_dn).toBe('OU=Staff,DC=corp,DC=local');
    expect('auth.ad.bind_password' in values).toBe(false);
  });

  it('учётка без группы доступа и неверный пароль', async () => {
    await open();
    fireEvent.change(screen.getByLabelText('Логин AD'), { target: { value: 'k.belova' } });
    fireEvent.change(screen.getByLabelText('Пароль', { selector: 'input' }), { target: { value: 'x' } });
    fireEvent.click(button('Проверить вход'));
    expect(await screen.findByText(/Не состоит в группе доступа/)).toBeTruthy();
    fireEvent.change(screen.getByLabelText('Пароль', { selector: 'input' }), { target: { value: 'wrong' } });
    fireEvent.click(button('Проверить вход'));
    expect(await screen.findByText(/Пользователь не найден или пароль неверный/)).toBeTruthy();
  });

  it('роли по группам: сначала подтверждение, затем поля групп', async () => {
    await open();
    expect(screen.queryByLabelText('Группа роли «Модератор»')).toBeNull();
    fireEvent.click(screen.getByRole('checkbox', { name: 'Назначать роли по группам AD' }));
    const dialog = await screen.findByRole('dialog', { name: 'Назначать роли по группам AD?' });
    expect(dialog.textContent).toContain('выданные вручную роли снимутся');
    fireEvent.click(within(dialog).getByRole('button', { name: 'Включить' }));
    const mod = (await screen.findByLabelText('Группа роли «Модератор»')) as HTMLInputElement;
    expect(mod.value).toContain('APP-Estimator-Moderators');
    expect(screen.getByText(/только вручную/)).toBeTruthy();
  });

  it('пароль сервисной учётки — «изменить», без значения', async () => {
    await open();
    fireEvent.click(screen.getByRole('button', { name: 'изменить' }));
    const field = screen.getByLabelText('Пароль сервисной учётки') as HTMLInputElement;
    expect(field.value).toBe('');
  });
});

describe('переход на Active Directory', () => {
  it('отчёт, решения по неоднозначным, step-up и режим AD с итогом', async () => {
    await open();
    fireEvent.click(button('Перейти на Active Directory…'));
    const dialog = await screen.findByRole('dialog', { name: 'Переход на Active Directory' });
    expect(dialog.textContent).toContain('Обратного перехода в интерфейсе нет');
    fireEvent.click(within(dialog).getByRole('button', { name: 'Сформировать отчёт' }));
    expect(await within(dialog).findByText('сопоставлено 5 · неоднозначно 2 · не найдено 2')).toBeTruthy();
    const apply = within(dialog).getByRole('button', { name: 'Осталось решить: 2' }) as HTMLButtonElement;
    expect(apply.disabled).toBe(true);
    fireEvent.click(within(dialog).getByRole('radio', { name: 'Орлова Мария Викторовна · m.orlova' }));
    const novikov = within(dialog).getByRole('radiogroup', { name: /Н. Новиков/ });
    fireEvent.click(within(novikov).getByRole('radio', { name: 'Не сопоставлять' }));
    fireEvent.click(within(dialog).getByRole('button', { name: 'Перейти на AD' }));
    await stepUp();
    expect(await screen.findByText('Сейчас: через Active Directory')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Перейти на Active Directory…' })).toBeNull();
    expect(screen.getByText('сопоставлено 6 · неоднозначно 2 (решены) · не найдено 3')).toBeTruthy();
    expect(screen.getByText(/Обратного переключателя нет/)).toBeTruthy();
  });
});
