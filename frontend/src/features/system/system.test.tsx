/** FE-060 · раздел «Система»: меню, «Состояние системы», красные баннеры, step-up. */
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { ApiError } from '../../shared/api/problem';
import { PERSONAS } from '../../shared/api/mocks/personas';
import { persona, server } from '../../test/setup';
import { HttpResponse, api, http, renderApp, renderUi } from '../../test/render';
import { sortComponents } from './health/HealthPage';
import { mfaWarningRoles, soleSuperadmin } from './layout/system';
import { isStepUpRequired, useStepUp } from './layout/useStepUp';

const account = (roles: string[], status = 'active') => ({ roles, status }) as never;

describe('правила раздела', () => {
  it('баннер — только когда активный суперадминистратор один', () => {
    expect(soleSuperadmin([account(['superadmin']), account(['admin'])])).toBe(true);
    expect(soleSuperadmin([account(['superadmin']), account(['superadmin'], 'blocked')])).toBe(true);
    expect(soleSuperadmin([account(['superadmin']), account(['superadmin'])])).toBe(false);
  });

  it('предупреждение FR-SA-04: роли, где обязательный по умолчанию TOTP отключён', () => {
    const policy = (p: object) => ({ 'security.mfa_policy': p });
    expect(mfaWarningRoles(policy({ admin: 'required', moderator: 'optional', user: 'optional' }))).toEqual([
      'moderator',
    ]);
    expect(mfaWarningRoles({})).toEqual([]);
  });

  it('карточки служб — в постоянном порядке', () => {
    const c = (name: string) => ({ name, ok: true, detail: null, checked_at: '' }) as never;
    expect(sortComponents([c('backup'), c('db'), c('smtp')]).map((x: { name: string }) => x.name)).toEqual([
      'db',
      'smtp',
      'backup',
    ]);
  });
});

describe('экран «Состояние системы»', () => {
  async function open() {
    persona.current = PERSONAS.superadmin;
    renderApp('/system');
    return screen.findByRole('list', { name: 'Состояние системы' });
  }

  it('меню раздела, версии и службы со словом «работает»', async () => {
    const list = await open();
    const menu = screen.getByRole('navigation', { name: 'Разделы системы' });
    expect([...menu.querySelectorAll('a')].map((a) => a.textContent)).toEqual([
      'Состояние системы',
      'Аутентификация',
      'Безопасность',
      'Почта (SMTP)',
      'Сроки хранения',
      'Суперадминистраторы и администраторы',
      'Аудиторы ИБ',
      'Анонимизация',
      'Реестр проектов',
      'Журнал аудита',
    ]);
    expect(within(menu).getByText('Состояние системы').getAttribute('aria-current')).toBe('page');
    expect(screen.getByText('1.0.0-rc.3')).toBeTruthy();
    expect(within(list).getByText('База данных')).toBeTruthy();
    expect(within(list).getAllByText('работает').length).toBeGreaterThan(3);
    expect(screen.getByText('Все службы работают')).toBeTruthy();
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('недоступная служба — словом и счётчиком', async () => {
    server.use(
      http.get(api('/system/health'), () =>
        HttpResponse.json({
          app_version: '1',
          schema_version: '1',
          components: [
            { name: 'db', ok: true, detail: null, checked_at: '2026-11-05T10:00:00Z' },
            { name: 'smtp', ok: false, detail: 'Нет ответа за 5 с', checked_at: '2026-11-05T10:00:00Z' },
          ],
        }),
      ),
    );
    const list = await open();
    expect(within(list).getByText('недоступен')).toBeTruthy();
    expect(within(list).getByText('Нет ответа за 5 с')).toBeTruthy();
    expect(screen.getByText('1 служба недоступна')).toBeTruthy();
  });

  it('красные баннеры: один суперадминистратор и отключённый TOTP', async () => {
    server.use(
      http.get(api('/system/admins'), () =>
        HttpResponse.json({
          items: [
            {
              id: '0190f000-0000-7000-8000-000000000001',
              login: 'superadmin',
              full_name: 'СА',
              email: null,
              roles: ['superadmin'],
              status: 'active',
              totp_enabled: true,
              last_login_at: null,
            },
          ],
        }),
      ),
      http.get(api('/system/settings/:section'), () =>
        HttpResponse.json({
          section: 'security',
          values: { 'security.mfa_policy': { admin: 'required', moderator: 'optional', presale: 'optional' } },
        }),
      ),
    );
    await open();
    const alerts = await screen.findAllByRole('alert');
    expect(alerts.map((a) => a.textContent).join(' ')).toContain('Заведите второго суперадминистратора');
    expect(alerts.map((a) => a.textContent).join(' ')).toContain('Модератор, Пресейл');
  });

  it('пункты следующих задач открываются в том же каркасе', async () => {
    persona.current = PERSONAS.superadmin;
    renderApp('/system/security');
    const menu = await screen.findByRole('navigation', { name: 'Разделы системы' });
    expect(within(menu).getByText('Безопасность').getAttribute('aria-current')).toBe('page');
  });
});

describe('step-up на критичных действиях', () => {
  function Harness({ action, onDone }: { action: () => Promise<string>; onDone: (v: string) => void }) {
    const { run, modal } = useStepUp();
    return (
      <>
        <button type="button" onClick={() => void run(action).then(onDone, (e: unknown) => onDone(String(e)))}>
          Действие
        </button>
        {modal}
      </>
    );
  }

  it('STEP_UP_REQUIRED → пароль и код → действие повторяется', async () => {
    let calls = 0;
    let result = '';
    const action = () => {
      calls += 1;
      return calls === 1
        ? Promise.reject(new ApiError(403, { code: 'STEP_UP_REQUIRED', title: 'step-up' } as never))
        : Promise.resolve('ok');
    };
    server.use(http.post(api('/auth/step-up'), () => new HttpResponse(null, { status: 204 })));
    renderUi(<Harness action={action} onDone={(v) => (result = v)} />);
    fireEvent.click(screen.getByRole('button', { name: 'Действие' }));
    const dialog = await screen.findByRole('dialog', { name: 'Подтвердите действие' });
    fireEvent.change(within(dialog).getByLabelText('Пароль', { selector: 'input' }), { target: { value: 'pw' } });
    fireEvent.paste(within(dialog).getByLabelText('Цифра 1'), { clipboardData: { getData: () => '123456' } });
    await waitFor(() => expect(result).toBe('ok'));
    expect(calls).toBe(2);
  });

  it('прочие ошибки не открывают окно', async () => {
    expect(isStepUpRequired(new ApiError(403, { code: 'FORBIDDEN', title: 'x' } as never))).toBe(false);
    let result = '';
    renderUi(<Harness action={() => Promise.reject(new Error('x'))} onDone={(v) => (result = v)} />);
    fireEvent.click(screen.getByRole('button', { name: 'Действие' }));
    await waitFor(() => expect(result).toBe('Error: x'));
    expect(screen.queryByRole('dialog')).toBeNull();
  });
});
