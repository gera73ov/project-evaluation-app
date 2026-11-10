/** FE-062 · «Безопасность», SIEM, «Почта (SMTP)», сводка и «Сроки хранения»: поля, проверки, step-up. */
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { PERSONAS } from '../../../shared/api/mocks/personas';
import { persona, server } from '../../../test/setup';
import { renderApp } from '../../../test/render';
import { isCidr, isTime, limits, lines } from './settings';

afterEach(() => server.events.removeAllListeners());

function capturePut(section: string) {
  const bodies: { values: Record<string, unknown> }[] = [];
  server.events.on('request:start', ({ request }) => {
    if (request.method === 'PUT' && new URL(request.url).pathname === `/api/v1/system/settings/${section}`)
      void request
        .clone()
        .json()
        .then((b: { values: Record<string, unknown> }) => bodies.push(b));
  });
  return bodies;
}

async function open(path: string, card: string) {
  persona.current = PERSONAS.superadmin;
  renderApp(path);
  return screen.findByRole('region', { name: card });
}

async function stepUp() {
  const dialog = await screen.findByRole('dialog', { name: 'Подтвердите действие' });
  fireEvent.change(within(dialog).getByLabelText('Пароль', { selector: 'input' }), { target: { value: 'pw' } });
  fireEvent.paste(within(dialog).getByLabelText('Цифра 1'), { clipboardData: { getData: () => '123456' } });
}

const save = (card: HTMLElement) => within(card).getByRole('button', { name: 'Сохранить…' }) as HTMLButtonElement;

describe('правила полей', () => {
  it('границы из settings.schema.json', () => {
    expect(limits('security.session', 'idle_minutes_admin')).toEqual({ min: 5, max: 60 });
    expect(limits('retention.periods', 'audit_months')).toEqual({ min: 6, max: 120 });
  });

  it('CIDR, строки и время', () => {
    expect(isCidr('10.0.0.0/8')).toBe(true);
    expect(isCidr('fd00::/8')).toBe(true);
    expect(isCidr('10.0.0.0/33')).toBe(false);
    expect(isCidr('300.0.0.1/8')).toBe(false);
    expect(isCidr('10.0.0.0')).toBe(false);
    expect(lines(' a \n\nb\na')).toEqual(['a', 'b']);
    expect([isTime('09:00'), isTime('24:00'), isTime('9:00')]).toEqual([true, false, false]);
  });
});

describe('«Безопасность»', () => {
  it('отключение обязательного TOTP — красное предупреждение; сохранение со step-up', async () => {
    const bodies = capturePut('security');
    const card = await open('/system/security', 'Политики безопасности');
    expect(save(card).disabled).toBe(true);
    expect(within(card).queryByRole('alert')).toBeNull();
    fireEvent.click(within(card).getByRole('switch', { name: 'Модератор' }));
    expect(within(card).getByRole('alert').textContent).toContain('Второй фактор отключён для ролей: Модератор');
    fireEvent.click(save(card));
    await stepUp();
    expect(await within(card).findByText('✓ Сохранено')).toBeTruthy();
    const last = bodies.at(-1)?.values ?? {};
    expect(last['security.mfa_policy']).toMatchObject({ moderator: 'optional', admin: 'required' });
    expect(last['security.password_policy']).toMatchObject({ min_length: 12, expiry_days: null });
    // баннер раздела берёт сохранённые значения
    await waitFor(() =>
      expect(
        screen
          .getAllByRole('alert')
          .map((a) => a.textContent)
          .join(' '),
      ).toContain('Второй фактор отключён для ролей: Модератор. Вход'),
    );
  });

  it('ошибки границ и сетей не дают сохранить', async () => {
    const bodies = capturePut('security');
    const card = await open('/system/security', 'Политики безопасности');
    fireEvent.change(within(card).getByLabelText('Минимальная длина'), { target: { value: '5' } });
    expect(await within(card).findByText('Целое от 8 до 128')).toBeTruthy();
    fireEvent.change(within(card).getByLabelText('Минимальная длина'), { target: { value: '14' } });
    fireEvent.change(within(card).getByRole('textbox', { name: 'Разрешённые сети админки суперадминистратора' }), {
      target: { value: '10.0.0.0/8\nвсе' },
    });
    expect(within(card).getByText(/Каждая строка — сеть/)).toBeTruthy();
    fireEvent.click(save(card));
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(bodies).toEqual([]);
  });

  it('срок пароля: включение даёт поле дней', async () => {
    const card = await open('/system/security', 'Политики безопасности');
    expect(within(card).queryByLabelText('Срок действия, дней')).toBeNull();
    fireEvent.click(within(card).getByRole('checkbox', { name: 'Ограничить срок действия пароля' }));
    expect((within(card).getByLabelText('Срок действия, дней') as HTMLInputElement).value).toBe('90');
    expect(save(card).disabled).toBe(false);
  });

  it('SIEM: включение требует сервер и сертификат УЦ', async () => {
    const card = await open('/system/security', 'Передача аудита в SIEM');
    fireEvent.click(within(card).getByRole('switch', { name: 'Передавать события аудита в SIEM' }));
    expect(await within(card).findByText('Укажите сервер')).toBeTruthy();
    expect(within(card).getByRole('alert').textContent).toBe('Обязательное поле');
  });
});

describe('«Почта (SMTP)» и сводка', () => {
  it('пароль только «изменить»; без шифрования — предупреждение; пароль уходит, только если введён', async () => {
    const bodies = capturePut('smtp');
    const card = await open('/system/smtp', 'Почтовый сервер');
    expect((within(card).getByLabelText('Сервер') as HTMLInputElement).value).toBe('mail.corp.local');
    expect(within(card).getByRole('button', { name: 'изменить' })).toBeTruthy();
    fireEvent.change(within(card).getByLabelText('Имя отправителя'), { target: { value: 'Оценки' } });
    fireEvent.click(save(card));
    await stepUp();
    expect(await within(card).findByText('✓ Сохранено')).toBeTruthy();
    expect(bodies.at(-1)?.values['smtp.server']).toMatchObject({ from_name: 'Оценки', host: 'mail.corp.local' });
    expect('smtp.password' in (bodies.at(-1)?.values ?? {})).toBe(false);
  });

  it('тестовое письмо: с параметрами формы; другой сервер — только с новым паролем (CR-009)', async () => {
    const bodies: { values: Record<string, unknown>; to: string }[] = [];
    server.events.on('request:start', ({ request }) => {
      if (request.method === 'POST' && new URL(request.url).pathname === '/api/v1/system/smtp/test')
        void request
          .clone()
          .json()
          .then((b: { values: Record<string, unknown>; to: string }) => bodies.push(b));
    });
    const card = await open('/system/smtp', 'Почтовый сервер');
    const send = () => within(card).getByRole('button', { name: 'Отправить тестовое письмо' }) as HTMLButtonElement;
    expect(send().disabled).toBe(true);
    fireEvent.change(within(card).getByLabelText('Адрес для тестового письма'), { target: { value: 'ib@corp.local' } });
    fireEvent.click(send());
    expect(await within(card).findByText('✓ Письмо на ib@corp.local принято сервером за 0,42 с')).toBeTruthy();
    expect(bodies[0]).toMatchObject({ to: 'ib@corp.local', values: { 'smtp.server': { host: 'mail.corp.local' } } });
    expect('smtp.password' in (bodies[0]?.values ?? {})).toBe(false);

    fireEvent.change(within(card).getByLabelText('Сервер'), { target: { value: 'mail-old.corp.local' } });
    expect(within(card).queryByRole('button', { name: 'изменить' })).toBeNull();
    expect(within(card).getByText(/сохранённый пароль туда не уйдёт/)).toBeTruthy();
    expect(send().disabled).toBe(true);
    fireEvent.change(within(card).getByLabelText('Пароль'), { target: { value: 'smtp-secret' } });
    fireEvent.click(send());
    expect(await within(card).findByText('✕ mail-old.corp.local:587: нет ответа за 10 с')).toBeTruthy();
    expect(bodies[1]?.values['smtp.password']).toBe('smtp-secret');
  });

  it('время сводки', async () => {
    const bodies = capturePut('digest');
    const card = await open('/system/smtp', 'Ежедневная сводка');
    fireEvent.change(within(card).getByLabelText(/Время отправки/), { target: { value: '08:30' } });
    fireEvent.click(save(card));
    await stepUp();
    await waitFor(() => expect(bodies.at(-1)?.values).toEqual({ 'digest.time': '08:30' }));
  });
});

describe('«Сроки хранения»', () => {
  it('границы и сохранение', async () => {
    const bodies = capturePut('retention');
    const card = await open('/system/retention', 'Сроки хранения');
    const trash = within(card).getByLabelText('Корзина, дней');
    fireEvent.change(trash, { target: { value: '400' } });
    expect(await within(card).findByText('Целое от 1 до 365')).toBeTruthy();
    fireEvent.change(trash, { target: { value: '60' } });
    fireEvent.click(save(card));
    await stepUp();
    await waitFor(() => expect(bodies.at(-1)?.values['retention.periods']).toMatchObject({ trash_days: 60 }));
  });
});
