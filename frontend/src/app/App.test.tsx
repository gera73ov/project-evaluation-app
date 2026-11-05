/** FE-003 · каркас: маршруты 8.1 на моках, гарды, меню по ролям, nonce, ошибки API. */
import { screen, waitFor } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { PERSONAS } from '../shared/api/mocks/personas';
import { ApiError, errorMessage, showsErrorId } from '../shared/api/problem';
import { readCsrfCookie } from '../shared/api/client';
import { cspNonce } from '../shared/ui/theme';
import { persona, server } from '../test/setup';
import { api, http, problem, renderApp } from '../test/render';
import { initials, shortName } from './AppShell';
import { matchPath } from './router';
import { ROUTES } from './routeTable';
import { safeNext } from './Routes';

describe('роутер', () => {
  it('matchPath: параметры и точное совпадение сегментов', () => {
    expect(matchPath('/projects/:id/settings', '/projects/42/settings')).toEqual({ id: '42' });
    expect(matchPath('/projects/:id', '/projects/42/settings')).toBeNull();
    expect(matchPath('/', '/')).toEqual({});
    expect(matchPath('/profile', '/profile/')).toEqual({});
  });

  it('next после входа — только внутренний путь', () => {
    expect(safeNext('/projects/1')).toBe('/projects/1');
    expect(safeNext('//evil.example')).toBe('/');
    expect(safeNext('https://evil.example')).toBe('/');
    expect(safeNext(null)).toBe('/');
  });
});

describe('гарды и меню', () => {
  it('без сессии — на вход с возвратом на исходный адрес', async () => {
    server.use(http.get(api('/me'), () => problem(401, 'UNAUTHENTICATED')));
    renderApp('/projects/abc/stats');
    await screen.findByRole('heading', { name: 'Вход' });
    expect(window.location.pathname).toBe('/login');
    expect(new URLSearchParams(window.location.search).get('next')).toBe('/projects/abc/stats');
  });

  it('сессия до подключения TOTP пускает только на подключение (FR-2FA-04)', async () => {
    server.use(http.get(api('/me'), () => problem(403, 'TOTP_ENROLL_REQUIRED')));
    renderApp('/profile');
    await screen.findByRole('heading', { name: 'Подключите вход по коду' });
    expect(window.location.pathname).toBe('/enroll-totp');
  });

  it('мастер не завершён — «Приложение настраивается» (FR-SA-02)', async () => {
    server.use(http.get(api('/me'), () => problem(503, 'APP_SETUP_IN_PROGRESS')));
    renderApp('/');
    await screen.findByRole('heading', { name: 'Приложение настраивается' });
  });

  it('эксперт видит только «Мои оценки»; пункты без права не рисуются', async () => {
    renderApp('/');
    const nav = await screen.findByRole('navigation', { name: 'Разделы' });
    expect([...nav.querySelectorAll('a')].map((a) => a.textContent)).toEqual(['Мои оценки']);
    expect(screen.getByRole('button', { name: 'Меню пользователя' }).textContent).toContain('И. Иванов');
  });

  it.each([
    ['presale_head', 'Портфель 🔒'],
    ['admin', 'Админка'],
    ['auditor', 'Журнал аудита'],
    ['superadmin', 'Система'],
  ] as const)('%s видит пункт «%s»', async (key, label) => {
    persona.current = new Map(Object.entries(PERSONAS)).get(key) ?? PERSONAS.expert;
    renderApp('/');
    const nav = await screen.findByRole('navigation', { name: 'Разделы' });
    expect([...nav.querySelectorAll('a')].map((a) => a.textContent)).toContain(label);
  });

  it('маршрут чужой системной роли — «Страница не найдена»', async () => {
    renderApp('/system');
    await screen.findByText('Страница не найдена.');
  });

  it('все маршруты карты 8.1 открываются на моках', async () => {
    persona.current = PERSONAS.superadmin;
    for (const route of ROUTES.filter((r) => r.access === 'private' && !r.roles)) {
      const path = route.path.replace(':id', 'p1');
      const { unmount } = renderApp(path);
      await waitFor(() => expect(document.querySelector('.hdr')).not.toBeNull());
      expect(screen.queryByText('Страница не найдена.'), path).toBeNull();
      unmount();
    }
  });
});

describe('API и безопасность', () => {
  it('тексты ошибок дословно из errors.yaml, error_id у 5xx', () => {
    const locked = new ApiError(429, { type: 't', title: 't', status: 429, code: 'LOGIN_LOCKED', error_id: 'e' });
    expect(errorMessage(locked)).toBe('Слишком много попыток, повторите через 15 минут');
    const failed = new ApiError(401, { type: 't', title: 't', status: 401, code: 'LOGIN_FAILED', error_id: 'e' });
    expect(errorMessage(failed, 'ad')).toBe(
      'Неверный логин или пароль. Если уверены в пароле — обратитесь к администратору',
    );
    const crash = new ApiError(500, { type: 't', title: 't', status: 500, code: 'WHATEVER', error_id: 'abc' });
    expect(errorMessage(crash)).toBe('Что-то пошло не так. Сообщите администратору код ошибки abc.');
    expect(showsErrorId(crash)).toBe(true);
    expect(showsErrorId(failed)).toBe(false);
    expect(errorMessage(new Error('x'))).toContain('Что-то пошло не так');
  });

  it('CSRF из cookie __Host-csrf, nonce из meta (SEC-WEB-03/04)', () => {
    expect(readCsrfCookie('a=1; __Host-csrf=tok%3D; b=2')).toBe('tok=');
    expect(readCsrfCookie('a=1')).toBeNull();
    const meta = document.createElement('meta');
    meta.name = 'csp-nonce';
    meta.content = 'n0nce';
    document.head.append(meta);
    expect(cspNonce()).toBe('n0nce');
    meta.remove();
    expect(cspNonce()).toBeUndefined();
  });

  it('аватар и короткое имя', () => {
    expect(initials('Иванов Иван')).toBe('ИИ');
    expect(shortName('Иванов Иван')).toBe('Иванов И.');
    expect(shortName('Суперадмин')).toBe('Суперадмин');
  });
});
