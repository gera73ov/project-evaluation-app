/** FE-006 · профиль и принудительное подключение TOTP на моках MSW. */
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { server } from '../../test/setup';
import { HttpResponse, api, http, problem, renderApp } from '../../test/render';
import { backupCodesText } from './BackupCodes';

const ME = {
  id: '00000000-0000-4000-8000-000000000001',
  login: 'i.ivanov',
  full_name: 'Иванов Иван',
  email: 'i.ivanov@example.test',
  source: 'local',
  timezone: 'Europe/Moscow',
  system_roles: [],
  totp_enabled: true,
  totp_required: false,
  mfa_passed: true,
  auth_mode: 'app',
  session_expires_at: '2026-11-05T20:00:00Z',
  idle_timeout_seconds: 1800,
};

const CODES = [
  '11112222',
  '33334444',
  '55556666',
  '77778888',
  '99990000',
  '12121212',
  '34343434',
  '56565656',
  '78787878',
  '90909090',
];

function withMe(overrides: Partial<typeof ME> = {}) {
  server.use(http.get(api('/me'), () => HttpResponse.json({ ...ME, ...overrides })));
}

async function openProfile() {
  renderApp('/profile');
  await screen.findByRole('heading', { name: 'Профиль', level: 1 });
}

function section(name: string): HTMLElement {
  return screen.getByRole('region', { name });
}

describe('профиль (FE-006)', () => {
  it('учётная запись: PATCH /me с ФИО и часовым поясом для локальной учётки', async () => {
    withMe();
    let body: unknown = null;
    server.use(
      http.patch(api('/me'), async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({ ...ME, full_name: 'Иванов Иван Петрович' });
      }),
    );
    await openProfile();
    const account = section('Учётная запись');
    const save = within(account).getByRole('button', { name: 'Сохранить' }) as HTMLButtonElement;
    expect(save.disabled).toBe(true);
    fireEvent.change(within(account).getByLabelText('ФИО'), { target: { value: 'Иванов Иван Петрович ' } });
    fireEvent.click(save);
    await waitFor(() => expect(body).toEqual({ full_name: 'Иванов Иван Петрович', timezone: 'Europe/Moscow' }));
  });

  it('учётка AD: ФИО только для чтения, раздела «Пароль» нет', async () => {
    withMe({ source: 'ad' });
    await openProfile();
    const fullName = within(section('Учётная запись')).getByLabelText('ФИО') as HTMLInputElement;
    expect(fullName.readOnly).toBe(true);
    expect(screen.getByText('Берётся из Active Directory')).toBeTruthy();
    expect(screen.queryByRole('region', { name: 'Пароль' })).toBeNull();
  });

  it('смена пароля: правила до отправки, текст CURRENT_PASSWORD_INVALID, затем успех', async () => {
    withMe();
    let body: unknown = null;
    let attempt = 0;
    server.use(
      http.post(api('/me/password'), async ({ request }) => {
        body = await request.json();
        attempt += 1;
        return attempt === 1 ? problem(400, 'CURRENT_PASSWORD_INVALID') : new HttpResponse(null, { status: 204 });
      }),
    );
    await openProfile();
    const box = section('Пароль');
    const submit = within(box).getByRole('button', { name: 'Сменить пароль' }) as HTMLButtonElement;
    const field = (label: string) => within(box).getByLabelText(label, { selector: 'input' });
    fireEvent.change(field('Текущий пароль'), { target: { value: 'old' } });
    fireEvent.change(field('Новый пароль'), { target: { value: 'bbbbbbbbbbbbbb' } });
    fireEvent.change(field('Повторите пароль'), { target: { value: 'bbbbbbbbbbbbb' } });
    expect(within(box).getByText('Пароли не совпадают')).toBeTruthy();
    expect(submit.disabled).toBe(true);
    fireEvent.change(field('Повторите пароль'), { target: { value: 'bbbbbbbbbbbbbb' } });
    fireEvent.click(submit);
    await within(box).findByText('Текущий пароль указан неверно.');
    expect(body).toEqual({ current_password: 'old', new_password: 'bbbbbbbbbbbbbb' });
    fireEvent.click(submit);
    await within(box).findByText('Пароль изменён. Остальные сессии завершены');
  });

  it('новые резервные коды показываются сеткой и скачиваются текстом', async () => {
    withMe();
    server.use(http.post(api('/me/backup-codes'), () => HttpResponse.json({ backup_codes: CODES })));
    await openProfile();
    fireEvent.click(within(section('Вход по коду (2FA)')).getByRole('button', { name: 'Новые резервные коды' }));
    const grid = await screen.findByLabelText('Резервные коды');
    expect(grid.querySelectorAll('span')).toHaveLength(10);
    expect(backupCodesText(['1', '2'], 'T')).toBe('T\n\n1\n2\n');
  });

  it('отключение TOTP: подтверждение, STEP_UP_REQUIRED → пароль и код → повтор запроса', async () => {
    withMe();
    let deletes = 0;
    let stepUpBody: unknown = null;
    server.use(
      http.delete(api('/me/totp'), () => {
        deletes += 1;
        return deletes === 1 ? problem(403, 'STEP_UP_REQUIRED') : new HttpResponse(null, { status: 204 });
      }),
      http.post(api('/auth/step-up'), async ({ request }) => {
        stepUpBody = await request.json();
        return new HttpResponse(null, { status: 204 });
      }),
    );
    await openProfile();
    fireEvent.click(within(section('Вход по коду (2FA)')).getByRole('button', { name: 'Отключить' }));
    const dialog = await screen.findByRole('dialog', { name: 'Отключить вход по коду?' });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Отключить' }));
    const stepUp = await screen.findByRole('dialog', { name: 'Подтвердите действие' });
    fireEvent.change(within(stepUp).getByLabelText('Пароль', { selector: 'input' }), { target: { value: 'pw' } });
    fireEvent.paste(within(stepUp).getByLabelText('Цифра 1'), { clipboardData: { getData: () => '123456' } });
    await waitFor(() => expect(deletes).toBe(2));
    expect(stepUpBody).toEqual({ code: '123456', password: 'pw', totp_only: false });
  });

  it('TOTP обязателен для роли — кнопки «Отключить» нет', async () => {
    withMe({ totp_required: true });
    await openProfile();
    const box = section('Вход по коду (2FA)');
    expect(within(box).queryByRole('button', { name: 'Отключить' })).toBeNull();
    expect(within(box).getByText('Для вашей роли вход по коду обязателен — отключить нельзя')).toBeTruthy();
  });

  it('подключение TOTP из профиля: QR, секрет, первый код, резервные коды', async () => {
    withMe({ totp_enabled: false });
    const bodies: unknown[] = [];
    server.use(
      http.post(api('/me/totp'), async ({ request }) => {
        const body = (await request.json()) as { code?: string };
        bodies.push(body);
        return body.code
          ? HttpResponse.json({ backup_codes: CODES })
          : HttpResponse.json({ otpauth_uri: 'otpauth://totp/Estimator:i.ivanov?secret=AAAAAAAA', secret: 'AAAAAAAA' });
      }),
    );
    await openProfile();
    fireEvent.click(within(section('Вход по коду (2FA)')).getByRole('button', { name: 'Подключить' }));
    await screen.findByRole('img', { name: 'QR-код для приложения-аутентификатора' });
    expect(screen.getByLabelText('Секрет').textContent).toBe('AAAAAAAA');
    fireEvent.paste(screen.getByLabelText('Цифра 1'), { clipboardData: { getData: () => '246810' } });
    await screen.findByLabelText('Резервные коды');
    expect(bodies).toEqual([{}, { code: '246810' }]);
  });

  it('сессии: завершить одну по id и все, кроме текущей', async () => {
    withMe();
    const ended: (string | null)[] = [];
    server.use(
      http.get(api('/me/sessions'), () =>
        HttpResponse.json({
          items: [
            {
              id: 'cur',
              current: true,
              user_agent: 'Firefox',
              ip: '10.0.0.1',
              created_at: '2026-11-05T08:00:00Z',
              last_seen_at: '2026-11-05T09:00:00Z',
            },
            {
              id: 'old',
              current: false,
              user_agent: null,
              ip: '10.0.0.2',
              created_at: '2026-11-04T08:00:00Z',
              last_seen_at: '2026-11-04T12:30:00Z',
            },
          ],
        }),
      ),
      http.delete(api('/me/sessions'), ({ request }) => {
        ended.push(new URL(request.url).searchParams.get('id'));
        return new HttpResponse(null, { status: 204 });
      }),
    );
    await openProfile();
    const box = section('Активные сессии');
    await within(box).findByText('Firefox');
    expect(within(box).getByText('текущая')).toBeTruthy();
    expect(within(box).getByText('04.11.2026 15:30')).toBeTruthy();
    fireEvent.click(within(box).getByRole('button', { name: 'Завершить' }));
    await waitFor(() => expect(ended).toEqual(['old']));
    fireEvent.click(within(box).getByRole('button', { name: 'Завершить все, кроме текущей' }));
    await waitFor(() => expect(ended).toEqual(['old', null]));
  });

  it('письма: переключатель сохраняет настройки PUT', async () => {
    withMe();
    let body: unknown = null;
    server.use(
      http.get(api('/me/notification-settings'), () =>
        HttpResponse.json({ notify_questions: true, notify_digest: false }),
      ),
      http.put(api('/me/notification-settings'), async ({ request }) => {
        const sent = (await request.json()) as Record<string, boolean>;
        body = sent;
        return HttpResponse.json(sent);
      }),
    );
    await openProfile();
    const digest = (await within(section('Письма')).findByLabelText('Ежедневная сводка')) as HTMLInputElement;
    expect(digest.checked).toBe(false);
    fireEvent.click(digest);
    await waitFor(() => expect(body).toEqual({ notify_questions: true, notify_digest: true }));
  });
});

describe('принудительное подключение TOTP (FR-2FA-04)', () => {
  it('после подключения и резервных кодов — на главную', async () => {
    let enrolled = false;
    server.use(
      http.get(api('/me'), () => (enrolled ? HttpResponse.json(ME) : problem(403, 'TOTP_ENROLL_REQUIRED'))),
      http.post(api('/auth/totp/enroll'), () =>
        HttpResponse.json({ otpauth_uri: 'otpauth://totp/Estimator:i.ivanov?secret=ABC', secret: 'ABC' }),
      ),
      http.post(api('/auth/totp/enroll/confirm'), () => {
        enrolled = true;
        return HttpResponse.json({ backup_codes: CODES });
      }),
    );
    renderApp('/projects');
    await screen.findByRole('heading', { name: 'Подключите вход по коду' });
    expect(window.location.pathname).toBe('/enroll-totp');
    fireEvent.paste(await screen.findByLabelText('Цифра 1'), { clipboardData: { getData: () => '135790' } });
    fireEvent.click(await screen.findByRole('button', { name: 'Продолжить' }));
    await waitFor(() => expect(window.location.pathname).toBe('/'));
  });
});
