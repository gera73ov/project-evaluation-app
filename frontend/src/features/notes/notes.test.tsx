/** FE-031 · закрытые заметки: вкладка по правам, «Добавить заметку», только чтение, TOTP. */
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { http } from 'msw';
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';

import { PROJECTS } from '../../shared/api/mocks/data';
import { uuidFrom } from '../../shared/api/mocks/ids';
import { PERSONAS } from '../../shared/api/mocks/personas';
import { persona, server } from '../../test/setup';
import { api, problem, renderApp } from '../../test/render';

const realHeight = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'clientHeight');
beforeAll(() => {
  Object.defineProperty(HTMLElement.prototype, 'clientHeight', {
    configurable: true,
    get(this: HTMLElement) {
      return this.classList.contains('tree-scroll') ? 900 : 0;
    },
  });
});
afterEach(() => server.events.removeAllListeners());
afterAll(() => {
  if (realHeight) Object.defineProperty(HTMLElement.prototype, 'clientHeight', realHeight);
});

const portal = PROJECTS.portal;

async function openPanel(who: 'expert' | 'moderator' | 'presale_head') {
  persona.current =
    who === 'expert' ? PERSONAS.expert : who === 'moderator' ? PERSONAS.moderator : PERSONAS.presale_head;
  const calls: { method: string; path: string; body: unknown }[] = [];
  server.events.on('request:start', ({ request }) => {
    const entry = { method: request.method, path: new URL(request.url).pathname, body: null as unknown };
    calls.push(entry);
    if (request.method !== 'GET')
      void request
        .clone()
        .json()
        .then((b) => (entry.body = b))
        .catch(() => undefined);
  });
  renderApp(`/projects/${portal.id}`);
  const grid = await screen.findByRole('treegrid', { name: 'Дерево оценки' });
  const row = (await within(grid).findByText('Обмен с 1С')).closest('[role="row"]') as HTMLElement;
  fireEvent.click(within(row).getByRole('button', { name: /^Обсуждение/ }));
  const panel = await screen.findByRole('region', { name: 'Обсуждение: Обмен с 1С' });
  return { panel, calls };
}

describe('закрытые заметки', () => {
  it('у эксперта вкладки нет в DOM, заметки не запрашиваются', async () => {
    const { panel, calls } = await openPanel('expert');
    await within(panel).findByText('Открытый вопрос');
    expect(within(panel).queryByRole('tab')).toBeNull();
    expect(panel.textContent).not.toContain('Заметки');
    expect(calls.some((c) => c.path.endsWith('/notes'))).toBe(false);
  });

  it('модератор: вкладка с числом, заметки фиолетовые, «Добавить заметку»', async () => {
    const { panel, calls } = await openPanel('moderator');
    const tab = await within(panel).findByRole('tab', { name: /Заметки\s*2/ });
    expect(panel.textContent).toContain('Обмен с 1С · Разработка › Бэкенд');
    fireEvent.click(tab);
    await within(panel).findByText(/Заказчик торгуется по интеграции/);
    expect(panel.querySelectorAll('.note-body')).toHaveLength(2);
    const input = within(panel).getByRole('textbox', { name: 'Закрытая заметка' });
    fireEvent.change(input, { target: { value: 'Скидка не больше 5%' } });
    fireEvent.click(within(panel).getByRole('button', { name: 'Добавить заметку' }));
    await within(panel).findByText('Скидка не больше 5%');
    expect(calls.find((c) => c.method === 'POST')?.body).toEqual({
      node_id: uuidFrom('node', 'portal', 'n-1c'),
      body: 'Скидка не больше 5%',
    });
    await within(panel).findByRole('tab', { name: /Заметки\s*3/ });
  });

  it('руководитель пресейла читает, но не пишет', async () => {
    const { panel } = await openPanel('presale_head');
    fireEvent.click(await within(panel).findByRole('tab', { name: /Заметки/ }));
    await within(panel).findByText(/Заказчик торгуется по интеграции/);
    expect(within(panel).queryByRole('button', { name: 'Добавить заметку' })).toBeNull();
    expect(within(panel).queryByRole('button', { name: 'Изменить' })).toBeNull();
  });

  it('без TOTP в сессии — «Подтвердите вход кодом» вместо списка', async () => {
    server.use(http.get(api('/projects/:id/notes'), () => problem(403, 'TOTP_REQUIRED')));
    const { panel } = await openPanel('moderator');
    fireEvent.click(await within(panel).findByRole('tab', { name: /Заметки/ }));
    await waitFor(() => expect(panel.textContent).toContain('Подтвердите вход кодом'));
    expect(within(panel).getByRole('button', { name: 'Ввести код' })).toBeTruthy();
    expect(within(panel).queryByRole('textbox', { name: 'Закрытая заметка' })).toBeNull();
  });
});
