/** FE-022 · таблица-дерево: порядок строк, свёртка, строка УП, чужие ветки, состояния листа, виртуализация. */
import { fireEvent, screen, within } from '@testing-library/react';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';

import type { components } from '../../../shared/api/client';
import { PROJECTS } from '../../../shared/api/mocks/data';
import { PERSONAS } from '../../../shared/api/mocks/personas';
import { dec } from '../../../shared/calc';
import { persona } from '../../../test/setup';
import { renderApp, renderUi } from '../../../test/render';
import { createTreeStore, type CalcSettings } from '../store/treeStore';
import { editRule } from '../WorkPage';
import { buildRows, indentOf } from './rows';
import { TreeTable, invalidReason, type TreeContext } from './TreeTable';

type Tree = components['schemas']['Tree'];
type Project = components['schemas']['Project'];

const SETTINGS: CalcSettings = {
  pmPercent: '10',
  quoteFigure: 'p80',
  detailLevel: 'medium',
  phases: [
    { id: 'A', name: 'Фаза А', isCrossCutting: false, inPmBase: true, enabled: true },
    { id: 'OFF', name: 'Выключена', isCrossCutting: false, inPmBase: true, enabled: false },
    { id: 'PM', name: 'УП', isCrossCutting: true, inPmBase: false, enabled: true },
  ],
  disciplines: [
    { id: 'd1', name: 'Бэкенд' },
    { id: 'd2', name: 'Фронтенд' },
  ],
};

function n(id: string, kind: string, phase: string, parent: string | null, extra: Record<string, unknown> = {}) {
  return {
    id,
    kind,
    phase_id: phase,
    parent_id: parent,
    discipline_id: null,
    title: id,
    position: id,
    multiplier: 1,
    version: 1,
    o: null,
    r: null,
    p: null,
    ...extra,
  };
}

function sample(): Tree {
  return {
    project_version: 1,
    nodes: [
      n('A', 'phase', 'A', null),
      n('OFF', 'phase', 'OFF', null),
      n('PM', 'phase', 'PM', null),
      n('A/d1', 'discipline', 'A', 'A', { discipline_id: 'd1', title: 'Бэкенд' }),
      n('A/d2', 'discipline', 'A', 'A', { discipline_id: 'd2', title: 'Фронтенд' }),
      n('m', 'item', 'A', 'A/d1', { discipline_id: 'd1', title: 'Модуль' }),
      n('l1', 'item', 'A', 'm', { discipline_id: 'd1', title: 'Пустой' }),
      n('l2', 'item', 'A', 'm', { discipline_id: 'd1', title: 'Неверный', o: '10', r: '8', p: '12' }),
      n('l3', 'item', 'A', 'm', { discipline_id: 'd1', title: 'Тройной', o: '1', r: '2', p: '3', multiplier: 3 }),
      n('f1', 'item', 'A', 'A/d2', { discipline_id: 'd2', title: 'Чужой лист', o: '2', r: '4', p: '6' }),
      n('x', 'item', 'OFF', 'OFF', { title: 'Скрытый' }),
    ],
    branch_statuses: [
      {
        phase_id: 'A',
        discipline_id: 'd1',
        status: 'draft',
        changed_by: null,
        changed_at: '',
        open_questions: 0,
        has_expert: true,
      },
      {
        phase_id: 'A',
        discipline_id: 'd2',
        status: 'done',
        changed_by: null,
        changed_at: '',
        open_questions: 0,
        has_expert: true,
      },
    ],
    totals: {},
  } as unknown as Tree;
}

const ctx: TreeContext = {
  canEdit: (d) => d === 'd1',
  withoutExpert: new Set(),
  disciplineNames: new Map([
    ['d1', 'Бэкенд'],
    ['d2', 'Фронтенд'],
  ]),
  nodeTypes: new Map(),
  tags: new Map(),
  pmPercent: '10',
  pmReason: 'один заказчик',
  settingsHref: null,
};

// jsdom не считает размеры: окно прокрутки дерева — 900 px (виртуализатор читает clientHeight)
const realHeight = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'clientHeight');
beforeAll(() => {
  Object.defineProperty(HTMLElement.prototype, 'clientHeight', {
    configurable: true,
    get(this: HTMLElement) {
      return this.classList.contains('tree-scroll') ? 900 : 0;
    },
  });
});
afterAll(() => {
  if (realHeight) Object.defineProperty(HTMLElement.prototype, 'clientHeight', realHeight);
});

describe('строки дерева', () => {
  it('порядок, выключенная фаза скрыта, УП — последней; свёрнутый узел прячет детей', () => {
    const store = createTreeStore();
    store.getState().load(sample(), SETTINGS);
    const { calc, children } = store.getState();
    if (!calc) throw new Error('нет расчёта');
    const rows = buildRows(calc, children, SETTINGS, new Set());
    expect(rows.map((r) => r.key)).toEqual(['A', 'A/d1', 'm', 'l1', 'l2', 'l3', 'A/d2', 'f1', 'pm']);
    expect(rows.map((r) => r.kind)).toEqual([
      'phase',
      'discipline',
      'node',
      'leaf',
      'leaf',
      'leaf',
      'discipline',
      'leaf',
      'pm',
    ]);
    expect(buildRows(calc, children, SETTINGS, new Set(['m'])).map((r) => r.key)).toEqual([
      'A',
      'A/d1',
      'm',
      'A/d2',
      'f1',
      'pm',
    ]);
  });

  it('отступ 8 + 16 на уровень, после 5-го не растёт; причина неверного листа', () => {
    expect([0, 1, 2, 5, 9].map(indentOf)).toEqual([8, 24, 40, 88, 88]);
    expect(invalidReason(dec('10'), dec('8'))).toBe('O > R');
    expect(invalidReason(dec('1'), dec('8'))).toBe('R > P');
  });
});

describe('кто правит ветку', () => {
  const project = { my_permissions: ['tree.write'], status: 'estimation' } as unknown as Project;
  const member = (role: string, discipline: string | null) =>
    ({ user: { id: 'me' }, role, discipline_id: discipline }) as components['schemas']['Member'];

  it('эксперт — свои дисциплины, модератор — все; без связи, в «Завершена» и без права — никто', () => {
    expect(editRule(project, [member('expert', 'd1')], 'me', false)('d1')).toBe(true);
    expect(editRule(project, [member('expert', 'd1')], 'me', false)('d2')).toBe(false);
    expect(editRule(project, [member('moderator', null)], 'me', false)('d2')).toBe(true);
    expect(editRule(project, [member('moderator', null)], 'me', true)('d2')).toBe(false);
    expect(editRule({ ...project, status: 'completed' }, [member('moderator', null)], 'me', false)('d1')).toBe(false);
    expect(editRule({ ...project, my_permissions: [] }, [member('moderator', null)], 'me', false)('d1')).toBe(false);
  });
});

describe('таблица', () => {
  it('состояния листа, ×N, чужая ветка, строка УП и свёртка', () => {
    const store = createTreeStore();
    store.getState().load(sample(), SETTINGS);
    renderUi(<TreeTable store={store} ctx={ctx} height={900} />);
    const grid = screen.getByRole('treegrid');
    const row = (title: string) => within(grid).getByText(title).closest('[role="row"]') as HTMLElement;

    expect(within(row('Пустой')).getByText('не учтён')).toBeTruthy();
    expect(row('Пустой').className).toContain('err');
    expect(within(row('Неверный')).getByText('O > R')).toBeTruthy();
    expect(within(row('Тройной')).getByText('×3').className).toBe('mul');
    expect(within(row('Фронтенд')).getByText(/чужая дисциплина/)).toBeTruthy();
    expect(within(row('Бэкенд')).queryByText(/чужая дисциплина/)).toBeNull();
    expect(within(row('Чужой лист')).getByText('2').className).toContain('ro');
    expect(within(row('Управление проектом')).getByText('10% от базы УП')).toBeTruthy();
    expect(within(row('Управление проектом')).getByText('Обоснование: один заказчик')).toBeTruthy();
    expect(within(grid).queryByText('Скрытый')).toBeNull();

    fireEvent.click(within(grid).getByRole('button', { name: 'Свернуть «Модуль»' }));
    expect(within(grid).queryByText('Пустой')).toBeNull();
    fireEvent.click(within(grid).getByRole('button', { name: 'Раскрыть «Модуль»' }));
    expect(within(grid).getByText('Пустой')).toBeTruthy();
  });

  it('5 000 узлов — в DOM не больше 150 строк (FR-TREE-15)', () => {
    const tree = sample();
    for (let i = 0; i < 5000; i++) {
      tree.nodes.push(
        n(`g${i}`, 'item', 'A', 'A/d1', {
          discipline_id: 'd1',
          position: `g${String(i).padStart(5, '0')}`,
          o: '1',
          r: '2',
          p: '3',
        }) as never,
      );
    }
    const store = createTreeStore();
    store.getState().load(tree, SETTINGS);
    renderUi(<TreeTable store={store} ctx={ctx} height={900} />);
    const rows = screen.getAllByRole('row');
    expect(rows.length).toBeGreaterThan(5);
    expect(rows.length).toBeLessThanOrEqual(150);
  });

  it('экран проекта у эксперта Бэкенда: итог фазы из расчёта, чужие ветки только для чтения', async () => {
    persona.current = PERSONAS.expert;
    renderApp(`/projects/${PROJECTS.portal.id}`);
    const grid = await screen.findByRole('treegrid', { name: 'Дерево оценки' });
    const row = (title: string) => within(grid).getByText(title).closest('[role="row"]') as HTMLElement;
    await within(grid).findByText('Разработка');
    expect(within(row('Разработка')).getByText('190,0')).toBeTruthy();
    expect(within(row('Фронтенд')).getByText(/чужая дисциплина/)).toBeTruthy();
    expect(within(row('Бэкенд')).queryByText(/чужая дисциплина/)).toBeNull();
  });
});
