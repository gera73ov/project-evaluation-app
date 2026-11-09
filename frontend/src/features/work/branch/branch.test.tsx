/** FE-029 · статус ветки и «Проверено»: готовность, «Отметить «Готово»», отметка, «Сведение» (GAP-10). */
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';

import { PROJECTS, disciplineId, phaseId } from '../../../shared/api/mocks/data';
import { PERSONAS } from '../../../shared/api/mocks/personas';
import { persona, server } from '../../../test/setup';
import { renderApp } from '../../../test/render';
import { createTreeStore } from '../store/treeStore';
import { branchReadiness } from './branch';

describe('готовность ветки', () => {
  it('пустые и неверные листья, открытые вопросы, есть ли узлы', () => {
    const store = createTreeStore();
    const node = (id: string, parent: string | null, kind: string, extra: object = {}) => ({
      id,
      parent_id: parent,
      kind,
      phase_id: 'ph',
      discipline_id: kind === 'phase' ? null : 'd',
      type_id: null,
      title: id,
      position: id,
      o: null,
      r: null,
      p: null,
      multiplier: 1,
      version: 1,
      ...extra,
    });
    store.getState().load(
      {
        project_version: 1,
        nodes: [
          node('ph', null, 'phase'),
          node('d', 'ph', 'discipline'),
          node('a', 'd', 'item', { o: '1', r: '2', p: '3', open_questions: 2 }),
          node('b', 'd', 'item'),
          node('c', 'd', 'item', { o: '5', r: '2', p: '3' }),
          node('e', 'ph', 'discipline'),
        ],
        branch_statuses: [],
      } as never,
      {
        pmPercent: '0',
        quoteFigure: 'e',
        detailLevel: 'medium',
        phases: [{ id: 'ph', name: 'ph', isCrossCutting: false, inPmBase: true, enabled: true }],
        disciplines: [{ id: 'd', name: 'd' }],
      },
    );
    expect(branchReadiness(store.getState(), 'd')).toEqual({ empty: 1, invalid: 1, open: 2, hasNodes: true });
    expect(branchReadiness(store.getState(), 'e')).toEqual({ empty: 0, invalid: 0, open: 0, hasNodes: false });
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

const portal = PROJECTS.portal;

async function openTree(who: 'expert' | 'moderator' = 'expert') {
  persona.current = who === 'expert' ? PERSONAS.expert : PERSONAS.moderator;
  const calls: { method: string; path: string; body: unknown }[] = [];
  server.events.on('request:start', ({ request }) => {
    if (request.method === 'GET') return;
    const entry = { method: request.method, path: new URL(request.url).pathname, body: null as unknown };
    calls.push(entry);
    void request
      .clone()
      .json()
      .then((b) => (entry.body = b))
      .catch(() => undefined);
  });
  renderApp(`/projects/${portal.id}`);
  const grid = await screen.findByRole('treegrid', { name: 'Дерево оценки' });
  await within(grid).findByText('Авторизация');
  const row = (title: string) => within(grid).getByText(title).closest('[role="row"]') as HTMLElement;
  return { grid, row, calls };
}

describe('статус ветки на рабочем экране', () => {
  it('«Отметить «Готово»» у черновика: PUT done, плашка «готово» и открытые вопросы', async () => {
    const { row, calls } = await openTree();
    fireEvent.click(within(row('Бэкенд')).getByRole('button', { name: 'Отметить «Готово»' }));
    await waitFor(() => expect(calls.find((c) => c.method === 'PUT')?.body).toEqual({ status: 'done' }));
    expect(calls.find((c) => c.method === 'PUT')?.path).toContain(
      `/branches/${phaseId('ph-dev')}/${disciplineId('d-backend')}/status`,
    );
    await waitFor(() => expect(row('Бэкенд').textContent).toContain('готово'));
    expect(row('Бэкенд').textContent).toContain('· 1 открытый вопрос');
    expect(within(row('Бэкенд')).queryByRole('button', { name: 'Отметить «Готово»' })).toBeNull();
  });

  it('пустой лист: кнопка неактивна, подсказка объясняет почему', async () => {
    const leaf = portal.nodes.find((n) => n.title === 'Авторизация');
    if (!leaf) throw new Error('нет листа');
    const saved = { o: leaf.o, r: leaf.r, p: leaf.p };
    Object.assign(leaf, { o: null, r: null, p: null });
    try {
      const { row } = await openTree();
      const button = within(row('Бэкенд')).getByRole('button', { name: 'Отметить «Готово»' });
      expect((button as HTMLButtonElement).disabled).toBe(true);
      expect(button.getAttribute('aria-description')).toBe('Нельзя отметить «Готово»: 1 пустой лист');
    } finally {
      Object.assign(leaf, saved);
    }
  });

  it('модератор: «Ветка не нужна» только у пустой ветки', async () => {
    const { row } = await openTree('moderator');
    fireEvent.click(within(row('Бэкенд')).getByRole('button', { name: /^Действия/ }));
    const menu = await screen.findByRole('menu');
    const item = within(menu).getByRole('menuitem', { name: /Ветка не нужна/ });
    expect(item.hasAttribute('data-disabled')).toBe(true);
    expect(item.textContent).toContain('в ветке есть узлы');
  });
});

describe('отметка «Проверено»', () => {
  it('ревьюер ставит ◐ (самопроверка), модератор — ✓; повторный щелчок снимает', async () => {
    const { row, calls } = await openTree();
    fireEvent.click(within(row('Авторизация')).getByRole('button', { name: 'Отметить «Проверено»: Авторизация' }));
    await waitFor(() => expect(calls.find((c) => c.path.endsWith('/review'))?.body).toEqual({ reviewed: true }));
    const self = await within(row('Авторизация')).findByRole('button', { name: 'Снять «Проверено»: Авторизация' });
    expect(self.querySelector('.half')).not.toBeNull();
    fireEvent.click(self);
    await waitFor(() =>
      expect(calls.filter((c) => c.path.endsWith('/review')).at(-1)?.body).toEqual({ reviewed: false }),
    );
    await within(row('Авторизация')).findByRole('button', { name: 'Отметить «Проверено»: Авторизация' });
  });

  it('модератор отмечает узел — отметка у всех листьев поддерева', async () => {
    const { row } = await openTree('moderator');
    fireEvent.click(within(row('Личный кабинет')).getByRole('button', { name: /^Отметить «Проверено»/ }));
    await within(row('Профиль дилера')).findByRole('button', { name: 'Снять «Проверено»: Профиль дилера' });
    expect(within(row('Авторизация')).getByRole('button', { name: /^Снять/ }).textContent).toBe('✓');
  });

  it('эксперт без права ревьюера в чужой дисциплине видит отметку без кнопки', async () => {
    const { grid } = await openTree();
    fireEvent.click(screen.getByRole('button', { name: /Мои ветки/, pressed: true }));
    await within(grid).findByText('Дашборд');
    const foreign = within(grid).getByText('Дашборд').closest('[role="row"]') as HTMLElement;
    expect(within(foreign).queryByRole('button', { name: /Проверено/ })).toBeNull();
  });
});

describe('«Сведение»: правка готовой ветки (GAP-10)', () => {
  it('перед первой правкой — диалог; «Отмена» не начинает ввод, «Продолжить» — и дальше без вопросов', async () => {
    const status = portal.branchStatuses.find(
      (b) => b.phase_id === phaseId('ph-dev') && b.discipline_id === disciplineId('d-backend'),
    ) as { status: string } | undefined;
    if (!status) throw new Error('нет ветки');
    const was = status.status;
    Object.assign(portal, { status: 'consolidation' });
    status.status = 'done';
    try {
      const { row } = await openTree();
      fireEvent.click(within(row('Авторизация')).getByRole('button', { name: 'O: 8' }));
      let dialog = await screen.findByRole('dialog', { name: 'Ветка «Бэкенд» готова' });
      expect(dialog.textContent).toContain('Ветка вернётся в черновик');
      fireEvent.click(within(dialog).getByRole('button', { name: 'Отмена' }));
      await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
      expect(within(row('Авторизация')).queryByRole('textbox', { name: 'O' })).toBeNull();

      fireEvent.click(within(row('Авторизация')).getByRole('button', { name: 'O: 8' }));
      dialog = await screen.findByRole('dialog', { name: 'Ветка «Бэкенд» готова' });
      fireEvent.click(within(dialog).getByRole('button', { name: 'Продолжить' }));
      const input = await within(row('Авторизация')).findByRole('textbox', { name: 'O' });
      fireEvent.keyDown(input, { key: 'Escape' });
      // второй раз в той же ветке — без вопроса
      fireEvent.click(within(row('Профиль дилера')).getByRole('button', { name: 'R: 16' }));
      expect(within(row('Профиль дилера')).getByRole('textbox', { name: 'R' })).toBeTruthy();
      expect(screen.queryByRole('dialog', { name: 'Ветка «Бэкенд» готова' })).toBeNull();
      // комментарий ветку не сбрасывает — без вопроса
    } finally {
      Object.assign(portal, { status: undefined });
      status.status = was;
    }
  });
});
