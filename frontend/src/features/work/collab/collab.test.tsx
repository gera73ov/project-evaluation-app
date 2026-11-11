/** FE-026 · совместная работа: захват и heartbeat, чужая ячейка и перехват, метки правок, конфликт 409. */
import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';

import { PROJECTS } from '../../../shared/api/mocks/data';
import { PERSONAS } from '../../../shared/api/mocks/personas';
import { FakeSocket } from '../../../test/fakeSocket';
import { persona, server } from '../../../test/setup';
import { api, http, problem, renderApp } from '../../../test/render';
import { MARK_MS, createCollabStore } from './collabStore';

const project = PROJECTS.portal.id;
const node = (title: string) => {
  const found = PROJECTS.portal.nodes.find((n) => n.title === title);
  if (!found) throw new Error(`нет узла ${title}`);
  return String(found.id);
};
const SMIRNOVA = { id: 'u-as', full_name: 'А. Смирнова', initials: 'АС', color: '#7f62a6' };
const IVANOV = { id: 'u-ii', full_name: 'И. Иванов', initials: 'ИИ' };

describe('состояние совместной работы', () => {
  it('чужие захваты, свои пропускаются; правка снимает захват и ставит метку на 10 с; присутствие', () => {
    const store = createCollabStore();
    const ev = (event: string, data: Record<string, unknown>) => ({ event, data });
    store
      .getState()
      .applyEvent(
        ev('cell.locked', { node_id: 'n', field: 'r', user: SMIRNOVA, expires_at: 'x', forced: false }),
        'me',
      );
    store
      .getState()
      .applyEvent(
        ev('cell.locked', { node_id: 'n', field: 'o', user: { ...IVANOV, id: 'me' }, expires_at: 'x', forced: false }),
        'me',
      );
    expect([...store.getState().locks.keys()]).toEqual(['n:r']);
    store
      .getState()
      .applyEvent(ev('node.updated', { node: { id: 'n' }, author: SMIRNOVA, changed_fields: ['r'] }), 'me', 1000);
    expect(store.getState().locks.size).toBe(0);
    expect(store.getState().marks.get('n')?.user.initials).toBe('АС');
    store.getState().applyEvent(ev('node.updated', { node: { id: 'm' }, author: { ...IVANOV, id: 'me' } }), 'me', 1000);
    expect(store.getState().marks.has('m')).toBe(false);
    store.getState().prune(1000 + MARK_MS - 1);
    expect(store.getState().marks.size).toBe(1);
    store.getState().prune(1000 + MARK_MS);
    expect(store.getState().marks.size).toBe(0);
    store
      .getState()
      .applyEvent(
        ev('cell.locked', { node_id: 'n', field: 'comment', user: SMIRNOVA, expires_at: 'x', forced: false }),
        'me',
      );
    store
      .getState()
      .applyEvent(ev('cell.unlocked', { node_id: 'n', field: 'comment', user_id: 'u-as', reason: 'released' }), 'me');
    expect(store.getState().locks.size).toBe(0);
    store.getState().applyEvent(ev('presence', { users: [SMIRNOVA, IVANOV] }), 'me');
    expect(store.getState().presence.map((p) => p.initials)).toEqual(['АС', 'ИИ']);
  });
});

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

/** Рабочий экран с управляемым сокетом: подписка подтверждена. */
async function open(who: 'expert' | 'moderator') {
  persona.current = who === 'expert' ? PERSONAS.expert : PERSONAS.moderator;
  FakeSocket.all = [];
  renderApp(`/projects/${project}`, { createSocket: FakeSocket.factory, backoff: () => 10, heartbeatMs: 40 });
  const grid = await screen.findByRole('treegrid', { name: 'Дерево оценки' });
  await within(grid).findByText('Авторизация');
  await waitFor(() => expect(FakeSocket.all.length).toBeGreaterThan(0));
  const socket = FakeSocket.last();
  act(() => socket.open());
  await waitFor(() => expect(socket.sent.some((c) => c.op === 'subscribe')).toBe(true));
  act(() => socket.ack('subscribe', { project_version: 21, channels: [], resync: false }));
  const row = (title: string) => within(grid).getByText(title).closest('[role="row"]') as HTMLElement;
  const push = (event: string, data: Record<string, unknown>, version?: number) =>
    act(() =>
      socket.push({
        type: 'event',
        event,
        channel: `project:${project}`,
        ts: '2026-11-09T10:00:00Z',
        ...(version ? { project_version: version } : {}),
        data,
      }),
    );
  return { socket, row, push, grid };
}

describe('совместная работа на рабочем экране', () => {
  it('lock при начале ввода, heartbeat пока ячейка в правке, unlock по Esc', async () => {
    const { socket, row } = await open('expert');
    fireEvent.click(within(row('Авторизация')).getByRole('button', { name: 'O: 8' }));
    await waitFor(() =>
      expect(socket.sent.find((c) => c.op === 'lock')).toMatchObject({
        project_id: project,
        node_id: node('Авторизация'),
        field: 'o',
      }),
    );
    act(() => socket.ack('lock', { expires_at: '2026-11-09T10:00:30Z' }));
    await waitFor(() =>
      expect(socket.sent.find((c) => c.op === 'heartbeat')).toMatchObject({
        locks: [{ node_id: node('Авторизация'), field: 'o' }],
      }),
    );
    fireEvent.keyDown(within(row('Авторизация')).getByRole('textbox', { name: 'O' }), { key: 'Escape' });
    expect(socket.sent.find((c) => c.op === 'unlock')).toMatchObject({ node_id: node('Авторизация'), field: 'o' });
  });

  it('чужая занятая ячейка: рамка с инициалами и подсказка; занятая при захвате — ввод не начинается', async () => {
    const { socket, row, push } = await open('expert');
    push('cell.locked', { node_id: node('Авторизация'), field: 'r', user: SMIRNOVA, expires_at: 'x', forced: false });
    const locked = within(row('Авторизация')).getByLabelText('Сейчас редактирует А. Смирнова');
    expect(locked.textContent).toContain('АС');
    expect(within(row('Авторизация')).queryByRole('button', { name: /^R:/ })).toBeNull();
    expect(screen.queryByText('Всё равно править')).toBeNull();

    fireEvent.click(within(row('Авторизация')).getByRole('button', { name: 'P: 20' }));
    await waitFor(() => expect(socket.sent.some((c) => c.op === 'lock' && c.field === 'p')).toBe(true));
    const command = socket.sent.find((c) => c.op === 'lock' && c.field === 'p');
    act(() =>
      socket.push({ type: 'error', op: 'lock', req_id: command?.req_id, code: 'CELL_LOCKED', locked_by: SMIRNOVA }),
    );
    await waitFor(() => expect(within(row('Авторизация')).queryByRole('textbox', { name: 'P' })).toBeNull());
    expect(within(row('Авторизация')).getAllByLabelText('Сейчас редактирует А. Смирнова')).toHaveLength(2);

    push('cell.unlocked', { node_id: node('Авторизация'), field: 'r', user_id: SMIRNOVA.id, reason: 'released' });
    expect(within(row('Авторизация')).getByRole('button', { name: 'R: 12' })).toBeTruthy();
  });

  it('модератор перехватывает чужую ячейку: lock с force', async () => {
    const { socket, row, push } = await open('moderator');
    push('cell.locked', { node_id: node('Авторизация'), field: 'r', user: IVANOV, expires_at: 'x', forced: false });
    fireEvent.click(within(row('Авторизация')).getByLabelText('Сейчас редактирует И. Иванов'));
    fireEvent.click(await screen.findByRole('button', { name: 'Всё равно править' }));
    await waitFor(() => expect(socket.sent.find((c) => c.op === 'lock')).toMatchObject({ field: 'r', force: true }));
    act(() => socket.ack('lock', { expires_at: 'x' }));
    expect(await within(row('Авторизация')).findByRole('textbox', { name: 'R' })).toBeTruthy();
  });

  it('чужая правка: подсветка строки и «АС изменил», присутствие в полосе', async () => {
    const { push, row } = await open('expert');
    const leaf = PROJECTS.portal.nodes.find((n) => n.title === 'Авторизация');
    push('node.updated', { node: { ...leaf, r: '14', version: 99 }, author: SMIRNOVA, changed_fields: ['r'] }, 22);
    await waitFor(() => expect(row('Авторизация').className).toContain('changed'));
    expect(within(row('Авторизация')).getByText('АС изменил')).toBeTruthy();
    expect(within(row('Авторизация')).getByRole('button', { name: 'R: 14' })).toBeTruthy();

    push('presence', { users: [SMIRNOVA, { ...IVANOV, id: 'u-x', full_name: 'П. Петров', initials: 'ПП' }] });
    const bar = screen.getByRole('banner', { name: 'Проект' });
    const avatars = within(bar).getByLabelText('Сейчас в проекте: 2');
    expect(avatars.textContent).toBe('АСПП');
  });

  it('конфликт 409: «Оставить моё» повторяет правку с текущей версией, «Принять» снимает своё', async () => {
    const bodies: { base_version: number; changes: Record<string, unknown> }[] = [];
    let conflicts = 1;
    server.use(
      http.patch(api('/nodes/:id'), async ({ request }) => {
        bodies.push((await request.json()) as (typeof bodies)[number]);
        if (conflicts-- > 0)
          return problem(409, 'FIELD_CONFLICT', {
            conflicts: [
              { field: 'r', current: '16', changed_by: { id: 'u-pp', full_name: 'П. Петров', initials: 'ПП' } },
            ],
            current_version: 9,
          });
        return problem(409, 'FIELD_CONFLICT', {
          conflicts: [{ field: 'r', current: '16', changed_by: 'П. Петров' }],
          current_version: 10,
        });
      }),
    );
    const { row } = await open('expert');
    fireEvent.click(within(row('Авторизация')).getByRole('button', { name: 'R: 12' }));
    const r = within(row('Авторизация')).getByRole('textbox', { name: 'R' });
    fireEvent.change(r, { target: { value: '18' } });
    fireEvent.keyDown(r, { key: 'Enter' });
    const dialog = await screen.findByRole('dialog', { name: 'Значение изменил П. Петров' });
    expect(dialog.textContent).toMatch(/Его:\s*16/);
    expect(dialog.textContent).toMatch(/Ваше:\s*18/);
    fireEvent.click(within(dialog).getByRole('button', { name: 'Оставить моё' }));
    await waitFor(() => expect(bodies).toHaveLength(2));
    expect(bodies[1]).toEqual({ base_version: 9, changes: { r: '18' } });

    const again = await screen.findByRole('dialog', { name: 'Значение изменил П. Петров' });
    fireEvent.click(within(again).getByRole('button', { name: 'Принять' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    expect(within(row('Авторизация')).getByRole('button', { name: 'R: 12' })).toBeTruthy();
    expect(bodies).toHaveLength(2);
  });
  it('чужая правка того же поля во время ввода: правка уходит с версией начала ввода (FE-091, FR-TREE-32)', async () => {
    const bodies: { base_version: number; changes: Record<string, unknown> }[] = [];
    server.use(
      http.patch(api('/nodes/:id'), async ({ request }) => {
        bodies.push((await request.json()) as (typeof bodies)[number]);
        return problem(409, 'FIELD_CONFLICT', {
          conflicts: [{ field: 'r', current: '14', changed_by: SMIRNOVA }],
          current_version: 99,
        });
      }),
    );
    const { push, row } = await open('expert');
    const leaf = PROJECTS.portal.nodes.find((n) => n.title === 'Авторизация');
    fireEvent.click(within(row('Авторизация')).getByRole('button', { name: 'R: 12' }));
    const r = within(row('Авторизация')).getByRole('textbox', { name: 'R' });
    fireEvent.change(r, { target: { value: '18' } });
    push('node.updated', { node: { ...leaf, r: '14', version: 99 }, author: SMIRNOVA, changed_fields: ['r'] }, 22);
    expect(within(row('Авторизация')).getByRole('textbox', { name: 'R' })).toHaveProperty('value', '18');
    fireEvent.keyDown(within(row('Авторизация')).getByRole('textbox', { name: 'R' }), { key: 'Enter' });
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toEqual({ base_version: leaf?.version, changes: { r: '18' } });
    expect(await screen.findByRole('dialog', { name: `Значение изменил ${SMIRNOVA.full_name}` })).toBeTruthy();
  });
  it('исключение из команды: экран закрывается сообщением со ссылкой на мои оценки (FE-091)', async () => {
    const { push } = await open('expert');
    push('access.revoked', { project_id: project, reason: 'removed_from_team' });
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('Доступ к проекту отозван');
    expect(alert.textContent).toContain('Модератор исключил вас из команды проекта');
    expect(within(alert).getByRole('link', { name: '← К моим оценкам' }).getAttribute('href')).toBe('/');
    expect(screen.queryByRole('treegrid')).toBeNull();
  });
});
