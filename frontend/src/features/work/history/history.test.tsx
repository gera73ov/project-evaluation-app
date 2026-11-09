/** FE-028 · история листа: разбор записей, панель у строки, «Вернуть» отправляет новую правку. */
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';

import { PROJECTS } from '../../../shared/api/mocks/data';
import { PERSONAS } from '../../../shared/api/mocks/personas';
import { persona, server } from '../../../test/setup';
import { renderApp } from '../../../test/render';
import { historyRows, type HistoryEntry } from './history';

const user = { id: 'u1', full_name: 'И. Иванов', initials: 'ИИ', is_active: true };
const entry = (id: string, action: HistoryEntry['action'], changes: Record<string, unknown>): HistoryEntry => ({
  id,
  created_at: '2026-11-01T08:07:00Z',
  user,
  action,
  changes: changes as HistoryEntry['changes'],
  node_version: 1,
  project_version: 1,
});

describe('строки истории', () => {
  it('вилка целиком из изменённых полей; текущее и что вернёт «Вернуть»', () => {
    const rows = historyRows(
      [
        entry('4', 'update', { o: ['30', '40'], r: ['40', '60'], p: ['60', '100'] }),
        entry('3', 'update', { comment_lines: [[], [{ tag_id: null, text: 'x' }]] }),
        entry('2', 'update', { p: ['48', '60'], o: ['24', '30'], r: ['32', '40'] }),
        entry('1', 'create', { o: [null, '24'], r: [null, '32'], p: [null, '48'] }),
      ],
      { o: '40', r: '60', p: '100.00' },
    );
    expect(rows.map((r) => r.kind)).toEqual(['fork', 'comment', 'fork', 'create']);
    expect(rows.map((r) => r.current)).toEqual([true, false, false, false]);
    expect(rows.at(0)?.before).toEqual({ o: '30', r: '40', p: '60' });
    expect(rows.at(2)?.revert).toEqual({ o: '30', r: '40', p: '60' });
    expect(rows.at(3)?.revert).toEqual({ o: '24', r: '32', p: '48' });
    expect(rows.at(3)?.before).toEqual({ o: null, r: null, p: null });
    expect(rows.at(1)?.revert).toBeNull();
  });

  it('частичная правка: остальные поля вилки берутся из более поздних значений', () => {
    const rows = historyRows([entry('2', 'update', { r: ['12', '14'] })], { o: '8', r: '14', p: '20' });
    expect(rows.at(0)?.before).toEqual({ o: '8', r: '12', p: '20' });
    expect(rows.at(0)?.current).toBe(true);
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

describe('панель истории на рабочем экране', () => {
  it('«История изменений» → записи как на макете; «Вернуть 30–40–60» — новая правка', async () => {
    persona.current = PERSONAS.expert;
    const patches: unknown[] = [];
    server.events.on('request:start', ({ request }) => {
      if (request.method === 'PATCH')
        void request
          .clone()
          .json()
          .then((b) => patches.push(b));
    });
    renderApp(`/projects/${PROJECTS.portal.id}`);
    const grid = await screen.findByRole('treegrid', { name: 'Дерево оценки' });
    await within(grid).findByText('Обмен с 1С');
    const row = () => within(grid).getByText('Обмен с 1С').closest('[role="row"]') as HTMLElement;
    fireEvent.click(within(row()).getByRole('button', { name: /^Действия/ }));
    fireEvent.click(within(await screen.findByRole('menu')).getByRole('menuitem', { name: 'История изменений' }));

    const panel = await screen.findByRole('dialog', { name: 'История: Обмен с 1С' });
    await waitFor(() => expect(panel.textContent).toContain('И. Иванов · 01.11.2026 11:07'));
    expect(panel.textContent).toContain('А. Смирнова (модератор) · 31.10.2026 18:20');
    expect((within(panel).getByRole('button', { name: 'текущее' }) as HTMLButtonElement).disabled).toBe(true);
    expect(within(panel).getByText('Комментарий изменён')).toBeTruthy();
    fireEvent.click(within(panel).getByRole('button', { name: 'Показать' }));
    expect(within(panel).getByText('Обмен по расписанию, раз в час')).toBeTruthy();
    expect(within(panel).getByRole('button', { name: 'Вернуть 24–32–48' })).toBeTruthy();

    fireEvent.click(within(panel).getByRole('button', { name: 'Вернуть 30–40–60' }));
    await waitFor(() => expect(patches).toHaveLength(1));
    expect(patches[0]).toMatchObject({ changes: { o: '30', r: '40', p: '60' } });
    await waitFor(() => expect(within(row()).getByRole('button', { name: 'P: 60' })).toBeTruthy());
    // правка попала в историю и стала текущей; прежнее значение можно вернуть
    expect(await within(panel).findByRole('button', { name: 'Вернуть 40–60–100' })).toBeTruthy();
    expect(within(panel).getAllByRole('button', { name: 'текущее' })).toHaveLength(1);

    fireEvent.keyDown(panel, { key: 'Escape' });
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'История: Обмен с 1С' })).toBeNull());
  });
});
