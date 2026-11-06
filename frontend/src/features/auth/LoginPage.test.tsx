/** FE-005 · вход и второй фактор: выноски 11.1 №1–7 на моках MSW. */
import { fireEvent, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';

import { server } from '../../test/setup';
import { HttpResponse, api, http, problem, renderApp } from '../../test/render';

/** Сессии нет, пока сервер не «выдал» её после входа. */
let signedIn = false;

beforeEach(() => {
  signedIn = false;
  server.use(
    // по умолчанию режим «Приложение»; тест AD переопределяет ответ
    http.get(api('/auth/options'), () => HttpResponse.json({ auth_mode: 'app' })),
    http.get(api('/me'), ({ request }) => {
      return signedIn
        ? undefined
        : problem(401, 'UNAUTHENTICATED', {
            instance: new URL(request.url).pathname,
          });
    }),
  );
});

async function openLogin(path = '/login') {
  renderApp(path);
  await screen.findByRole('heading', { name: 'Вход' });
}

function fillCredentials(login = 'i.ivanov', password = 'xxxxxxxx') {
  fireEvent.change(screen.getByLabelText('Логин'), {
    target: { value: login },
  });
  fireEvent.change(screen.getByLabelText('Пароль'), {
    target: { value: password },
  });
}

function submit() {
  fireEvent.click(screen.getByRole('button', { name: 'Войти' }));
}

function pasteCode(code: string) {
  const first = screen.getByLabelText('Цифра 1');
  fireEvent.paste(first, { clipboardData: { getData: () => code } });
}

describe('экран входа (11.1)', () => {
  it('№1: «Войти» недоступна, пока логин или пароль пусты', async () => {
    await openLogin();
    const button = screen.getByRole('button', { name: 'Войти' });
    expect((button as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByLabelText('Логин'), {
      target: { value: 'i.ivanov' },
    });
    expect((button as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByLabelText('Пароль'), {
      target: { value: 'x' },
    });
    expect((button as HTMLButtonElement).disabled).toBe(false);
  });

  it('№2: повторное нажатие во время проверки не шлёт второй запрос', async () => {
    let calls = 0;
    server.use(
      http.post(api('/auth/login'), async () => {
        calls += 1;
        await new Promise((r) => setTimeout(r, 30));
        return problem(401, 'LOGIN_FAILED');
      }),
    );
    await openLogin();
    fillCredentials();
    const form = screen.getByRole('button', { name: 'Войти' }).closest('form');
    if (!form) throw new Error('нет формы');
    fireEvent.submit(form);
    fireEvent.submit(form);
    await screen.findByText('Неверный логин или пароль');
    expect(calls).toBe(1);
  });

  it('№3–4: неверный пароль — текст errors.yaml, пароль очищен, логин остался', async () => {
    server.use(http.post(api('/auth/login'), () => problem(401, 'LOGIN_FAILED', { auth_mode: 'app' })));
    await openLogin();
    fillCredentials();
    submit();
    await screen.findByText('Неверный логин или пароль');
    expect((screen.getByLabelText('Пароль') as HTMLInputElement).value).toBe('');
    expect((screen.getByLabelText('Логин') as HTMLInputElement).value).toBe('i.ivanov');
    expect(screen.getByRole('link', { name: 'Забыли пароль?' })).toBeTruthy();
  });

  it('№5: режим AD — подсказка про пароль компьютера, нет «Забыли пароль?», текст для AD', async () => {
    server.use(http.post(api('/auth/login'), () => problem(401, 'LOGIN_FAILED', { auth_mode: 'ad' })));
    await openLogin();
    fillCredentials();
    submit();
    await screen.findByText('Неверный логин или пароль. Если уверены в пароле — обратитесь к администратору');
    expect(screen.getByText(/под которыми входите в компьютер/)).toBeTruthy();
    expect(screen.queryByRole('link', { name: 'Забыли пароль?' })).toBeNull();
    expect(screen.getByText('Учётная запись компании')).toBeTruthy();
  });

  it('режим AD известен до входа из GET /auth/options (CR-001)', async () => {
    server.use(http.get(api('/auth/options'), () => HttpResponse.json({ auth_mode: 'ad' })));
    await openLogin();
    await screen.findByText('Учётная запись компании');
    expect(screen.queryByRole('link', { name: 'Забыли пароль?' })).toBeNull();
  });

  it('блокировка и недоступный сервис аутентификации (FR-LOCK-05, FR-AUTH-AD-13)', async () => {
    server.use(http.post(api('/auth/login'), () => problem(429, 'LOGIN_LOCKED')));
    await openLogin();
    fillCredentials();
    submit();
    await screen.findByText('Слишком много попыток, повторите через 15 минут');

    server.use(http.post(api('/auth/login'), () => problem(503, 'AUTH_SERVICE_UNAVAILABLE')));
    fillCredentials();
    submit();
    await screen.findByText('Сервис аутентификации временно недоступен');
  });

  it('№6: код TOTP — вставка из буфера отправляет сразу, затем переход на next', async () => {
    let totpBody: unknown = null;
    server.use(
      http.post(api('/auth/login'), () =>
        HttpResponse.json({
          step: 'totp',
          login_token: 'tok',
          expires_in: 300,
        }),
      ),
      http.post(api('/auth/totp'), async ({ request }) => {
        totpBody = await request.json();
        signedIn = true;
        return HttpResponse.json({ step: 'done' });
      }),
    );
    await openLogin('/login?next=%2Fprofile');
    fillCredentials();
    submit();
    await screen.findByRole('heading', { name: 'Подтвердите вход' });
    pasteCode('12 34 56');
    await waitFor(() => expect(window.location.pathname).toBe('/profile'));
    expect(totpBody).toEqual({ login_token: 'tok', code: '123456' });
  });

  it('№7: неверный код — сообщение и пустые клетки; истёкший шаг — назад ко входу', async () => {
    server.use(
      http.post(api('/auth/login'), () => HttpResponse.json({ step: 'totp', login_token: 'tok' })),
      http.post(api('/auth/totp'), () => problem(401, 'TOTP_INVALID')),
    );
    await openLogin();
    fillCredentials();
    submit();
    await screen.findByRole('heading', { name: 'Подтвердите вход' });
    pasteCode('111111');
    await screen.findByText('Неверный код. Проверьте время на телефоне и введите новый код.');
    expect((screen.getByLabelText('Цифра 1') as HTMLInputElement).value).toBe('');

    server.use(http.post(api('/auth/totp'), () => problem(401, 'LOGIN_STEP_EXPIRED')));
    pasteCode('222222');
    await screen.findByRole('heading', { name: 'Вход' });
    expect(screen.getByText('Время на ввод кода истекло. Войдите снова.')).toBeTruthy();
  });

  it('резервный код: 8 цифр, отправляется полем backup_code', async () => {
    let totpBody: unknown = null;
    server.use(
      http.post(api('/auth/login'), () => HttpResponse.json({ step: 'totp', login_token: 'tok' })),
      http.post(api('/auth/totp'), async ({ request }) => {
        totpBody = await request.json();
        signedIn = true;
        return HttpResponse.json({ step: 'done' });
      }),
    );
    await openLogin();
    fillCredentials();
    submit();
    fireEvent.click(await screen.findByRole('button', { name: 'Использовать резервный код' }));
    const field = screen.getByLabelText('Резервный код');
    const confirm = screen.getByRole('button', { name: 'Подтвердить' });
    fireEvent.change(field, { target: { value: '1234-567' } });
    expect((confirm as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(field, { target: { value: '12345678' } });
    fireEvent.click(confirm);
    await waitFor(() => expect(window.location.pathname).toBe('/'));
    expect(totpBody).toEqual({ login_token: 'tok', backup_code: '12345678' });
  });

  it('step=enroll ведёт на подключение TOTP (FR-2FA-04)', async () => {
    server.use(
      http.post(api('/auth/login'), () => {
        signedIn = true;
        return HttpResponse.json({ step: 'enroll' });
      }),
      http.get(api('/me'), () => (signedIn ? problem(403, 'TOTP_ENROLL_REQUIRED') : problem(401, 'UNAUTHENTICATED'))),
    );
    await openLogin();
    fillCredentials();
    submit();
    await screen.findByRole('heading', { name: 'Подключите вход по коду' });
    expect(window.location.pathname).toBe('/enroll-totp');
  });

  it('step=password_change: только смена пароля, затем подключение TOTP (CR-003)', async () => {
    let state: 'expired' | 'enroll' = 'expired';
    let body: unknown = null;
    server.use(
      http.post(api('/auth/login'), () => {
        signedIn = true;
        return HttpResponse.json({ step: 'password_change', expires_in: 900 });
      }),
      http.get(api('/me'), () => {
        if (!signedIn) return problem(401, 'UNAUTHENTICATED');
        return problem(403, state === 'expired' ? 'PASSWORD_CHANGE_REQUIRED' : 'TOTP_ENROLL_REQUIRED');
      }),
      http.post(api('/me/password'), async ({ request }) => {
        body = await request.json();
        state = 'enroll';
        return new HttpResponse(null, { status: 204 });
      }),
    );
    await openLogin();
    fillCredentials();
    submit();
    await screen.findByRole('heading', { name: 'Срок действия пароля истёк' });
    expect(window.location.pathname).toBe('/change-password');
    const button = screen.getByRole('button', { name: 'Сменить пароль' });
    fireEvent.change(screen.getByLabelText('Текущий пароль'), { target: { value: 'old password 1' } });
    fireEvent.change(screen.getByLabelText('Новый пароль'), { target: { value: 'new long password 2' } });
    fireEvent.change(screen.getByLabelText('Повторите пароль'), { target: { value: 'new long password' } });
    expect((button as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByLabelText('Повторите пароль'), { target: { value: 'new long password 2' } });
    fireEvent.click(button);
    await screen.findByRole('heading', { name: 'Подключите вход по коду' });
    expect(body).toEqual({ current_password: 'old password 1', new_password: 'new long password 2' });
    expect(window.location.pathname).toBe('/enroll-totp');
  });

  it('с истёкшим паролем другие экраны недоступны, выход работает', async () => {
    signedIn = true;
    let loggedOut = false;
    server.use(
      http.get(api('/me'), () => (signedIn ? problem(403, 'PASSWORD_CHANGE_REQUIRED') : problem(401, 'UNAUTHENTICATED'))),
      http.post(api('/auth/logout'), () => {
        loggedOut = true;
        signedIn = false;
        return new HttpResponse(null, { status: 204 });
      }),
    );
    renderApp('/profile');
    await screen.findByRole('heading', { name: 'Срок действия пароля истёк' });
    expect(window.location.pathname).toBe('/change-password');
    fireEvent.click(screen.getByRole('button', { name: 'Выйти' }));
    await waitFor(() => expect(window.location.pathname).toBe('/login'));
    expect(loggedOut).toBe(true);
  });

  it('мастер не завершён — экран «Приложение настраивается»', async () => {
    server.use(http.post(api('/auth/login'), () => problem(503, 'APP_SETUP_IN_PROGRESS')));
    await openLogin();
    fillCredentials();
    submit();
    await screen.findByRole('heading', { name: 'Приложение настраивается' });
  });
});

describe('пароль: восстановление и смена по ссылке', () => {
  it('запрос ссылки всегда отвечает одинаково (без раскрытия учётных записей)', async () => {
    server.use(http.post(api('/auth/password/forgot'), () => new HttpResponse(null, { status: 202 })));
    renderApp('/password/forgot');
    await screen.findByRole('heading', { name: 'Восстановление пароля' });
    fireEvent.change(screen.getByLabelText('Логин или email'), {
      target: { value: 'nobody' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Отправить ссылку' }));
    await screen.findByText('Если такая учётная запись есть, мы отправили письмо');
  });

  it('новый пароль: правило длины и совпадение проверяются до отправки', async () => {
    let body: unknown = null;
    server.use(
      http.post(api('/auth/password/reset'), async ({ request }) => {
        body = await request.json();
        return new HttpResponse(null, { status: 204 });
      }),
    );
    renderApp('/password/reset?token=abc');
    await screen.findByRole('heading', { name: 'Новый пароль' });
    const submitButton = screen.getByRole('button', { name: 'Сменить пароль' });
    fireEvent.change(screen.getByLabelText('Новый пароль', { selector: 'input' }), { target: { value: 'short' } });
    fireEvent.change(screen.getByLabelText('Повторите пароль'), {
      target: { value: 'short' },
    });
    fireEvent.click(submitButton);
    expect(await screen.findByText('Пароль короче 12 символов')).toBeTruthy();
    expect(body).toBeNull();

    fireEvent.change(screen.getByLabelText('Новый пароль', { selector: 'input' }), {
      target: { value: 'aaaaaaaaaaaaaa' },
    });
    fireEvent.change(screen.getByLabelText('Повторите пароль'), {
      target: { value: 'aaaaaaaaaaaaa' },
    });
    fireEvent.click(submitButton);
    expect(await screen.findByText('Пароли не совпадают')).toBeTruthy();

    fireEvent.change(screen.getByLabelText('Повторите пароль'), {
      target: { value: 'aaaaaaaaaaaaaa' },
    });
    fireEvent.click(submitButton);
    await screen.findByText('Пароль изменён. Войдите с новым паролем');
    expect(body).toMatchObject({ token: 'abc', password: 'aaaaaaaaaaaaaa' });
  });

  it('просроченная ссылка — текст TOKEN_INVALID', async () => {
    server.use(http.post(api('/auth/password/reset'), () => problem(400, 'TOKEN_INVALID')));
    renderApp('/password/reset?token=old');
    await screen.findByRole('heading', { name: 'Новый пароль' });
    fireEvent.change(screen.getByLabelText('Новый пароль', { selector: 'input' }), {
      target: { value: 'aaaaaaaaaaaaaa' },
    });
    fireEvent.change(screen.getByLabelText('Повторите пароль'), {
      target: { value: 'aaaaaaaaaaaaaa' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Сменить пароль' }));
    await screen.findByText('Ссылка недействительна или устарела. Запросите новую.');
  });
});
