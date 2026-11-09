/** FE-024 · поиск, чипы-фильтры, «Показать: до фаз…», сохранение вида (FR-TREE-12, FR-TREE-14). */
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';

import type { components } from '../../../shared/api/client';
import { PROJECTS } from '../../../shared/api/mocks/data';
import { PERSONAS } from '../../../shared/api/mocks/personas';
import { dec } from '../../../shared/calc';
import { persona, server } from '../../../test/setup';
import { HttpResponse, api, http, renderApp } from '../../../test/render';
import { createTreeStore, type CalcSettings } from '../store/treeStore';
import { buildRows } from '../tree/rows';
import { chipCounts, collapseTo, unaccountedLeaves, visibleNodes, type FilterInput, type FilterKey } from './filters';
import { MAX_COLLAPSED, parseView, serializeView } from './viewState';

type Tree = components['schemas']['Tree'];

const SETTINGS: CalcSettings = {
  pmPercent: '10',
  quoteFigure: 'p80',
  detailLevel: 'medium',
  phases: [
    { id: 'A', name: 'Фаза А', isCrossCutting: false, inPmBase: true, enabled: true },
    { id: 'PM', name: 'УП', isCrossCutting: true, inPmBase: false, enabled: true },
  ],
  disciplines: [
    { id: 'd1', name: 'Бэкенд' },
    { id: 'd2', name: 'Фронтенд' },
  ],
};

function n(id: string, kind: string, parent: string | null, extra: Record<string, unknown> = {}) {
  return {
    id,
    kind,
    phase_id: id === 'PM' ? 'PM' : 'A',
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

function store() {
  const tree = {
    project_version: 1,
    nodes: [
      n('A', 'phase', null),
      n('PM', 'phase', null),
      n('A/d1', 'discipline', 'A', { discipline_id: 'd1', title: 'Бэкенд' }),
      n('A/d2', 'discipline', 'A', { discipline_id: 'd2', title: 'Фронтенд' }),
      n('m', 'item', 'A/d1', { discipline_id: 'd1', title: 'Модуль' }),
      n('l1', 'item', 'm', { discipline_id: 'd1', title: 'Пустой' }),
      n('l2', 'item', 'm', { discipline_id: 'd1', title: 'Неверный', o: '10', r: '8', p: '12' }),
      n('l3', 'item', 'm', {
        discipline_id: 'd1',
        title: 'Готовый',
        o: '1',
        r: '2',
        p: '3',
        reviewed_by: { id: 'u' },
        self_review: true,
        comment_lines: [{ tag_id: 'risk', text: 'Зависит от API банка' }],
      }),
      n('f1', 'item', 'A/d2', { discipline_id: 'd2', title: 'Экран', o: '50', r: '60', p: '90', open_questions: 2 }),
    ],
    branch_statuses: [],
    totals: {},
  } as unknown as Tree;
  const s = createTreeStore();
  s.getState().load(tree, SETTINGS);
  const { calc, nodes, children } = s.getState();
  if (!calc) throw new Error('нет расчёта');
  return { calc, nodes, children };
}

const INPUT: FilterInput = { myDisciplines: new Set(['d1']), largeThreshold: dec('40'), riskTags: new Set(['risk']) };

describe('фильтры дерева', () => {
  it('поиск с 2 символов по названию и комментарию, найденное — с родителями', () => {
    const { calc, nodes, children } = store();
    expect(visibleNodes(calc, nodes, new Set(), 'н', INPUT)).toBeNull();
    const byTitle = visibleNodes(calc, nodes, new Set(), 'НЕВЕР', INPUT);
    expect([...(byTitle ?? [])].sort()).toEqual(['A', 'A/d1', 'l2', 'm']);
    const byComment = visibleNodes(calc, nodes, new Set(), 'банка', INPUT);
    expect(byComment?.has('l3')).toBe(true);
    const rows = buildRows(calc, children, SETTINGS, new Set(['m']), byTitle);
    // свёртка под фильтром не действует, строка УП остаётся
    expect(rows.map((r) => r.key)).toEqual(['A', 'A/d1', 'm', 'l2', 'pm']);
    expect(rows.every((r) => r.filtered || r.kind === 'pm')).toBe(true);
  });

  it('чипы по одному и вместе, числа строк, неучтённые листья, «до фаз»', () => {
    const { calc, nodes } = store();
    const only = (...keys: FilterKey[]) =>
      [...(visibleNodes(calc, nodes, new Set(keys), '', INPUT) ?? [])].filter((id) => /^(l|f)/.test(id)).sort();
    expect(only('unestimated')).toEqual(['l1', 'l2']);
    expect(only('large')).toEqual(['f1']);
    expect(only('unreviewed')).toEqual(['f1', 'l1', 'l2']);
    expect(only('selfReview')).toEqual(['l3']);
    expect(only('questions')).toEqual(['f1']);
    expect(only('risk')).toEqual(['l3']);
    expect(only('mine', 'unreviewed')).toEqual(['l1', 'l2']);
    const counts = chipCounts(calc, nodes, INPUT);
    expect(counts.get('unestimated')).toBe(2);
    expect(counts.get('unreviewed')).toBe(3);
    expect(unaccountedLeaves(calc)).toEqual({ empty: 1, invalid: 1 });
    expect([...collapseTo(calc, 'phases')].sort()).toEqual(['A', 'PM']);
    expect([...collapseTo(calc, 'disciplines')].sort()).toEqual(['A/d1', 'A/d2']);
  });

  it('состояние вида: первый вход, разбор, обрезка до 64 КБ', () => {
    expect([...parseView({}, true).filters]).toEqual(['mine']);
    expect([...parseView({}, false).filters]).toEqual([]);
    const view = parseView({ filters: ['questions', 'чужое'], collapsed: ['a', 1] }, true);
    expect([...view.filters]).toEqual(['questions']);
    expect([...view.collapsed]).toEqual(['a']);
    const many = new Set(Array.from({ length: MAX_COLLAPSED + 50 }, (_, i) => `00000000-0000-0000-0000-${i}`));
    const body = serializeView({ collapsed: many, filters: new Set() });
    expect(body.collapsed).toHaveLength(MAX_COLLAPSED);
    expect(JSON.stringify(body).length).toBeLessThan(64 * 1024);
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
afterAll(() => {
  if (realHeight) Object.defineProperty(HTMLElement.prototype, 'clientHeight', realHeight);
});

const id = PROJECTS.portal.id;

describe('полоса инструментов на рабочем экране', () => {
  it('эксперт: «Мои ветки» включён при первом входе, итоги полосы от фильтров не меняются', async () => {
    persona.current = PERSONAS.expert;
    renderApp(`/projects/${id}`);
    const tools = await screen.findByRole('toolbar', { name: 'Поиск и фильтры' });
    expect(
      within(tools)
        .getByRole('button', { name: /Мои ветки/ })
        .getAttribute('aria-pressed'),
    ).toBe('true');
    const grid = screen.getByRole('treegrid');
    expect(within(grid).queryByText('Фронтенд')).toBeNull();
    const bar = screen.getByRole('banner', { name: 'Проект' });
    expect(within(bar).getByText('406,5')).toBeTruthy();
    fireEvent.click(within(tools).getByRole('button', { name: /С вопросами/ }));
    expect(within(bar).getByText('406,5')).toBeTruthy();
  });

  it('модератор: «Мои ветки» выключен, поиск подсвечивает, «до фаз» сворачивает, вид сохраняется', async () => {
    persona.current = PERSONAS.moderator;
    const saved: unknown[] = [];
    server.use(
      http.put(api('/me/view-state/:id'), async ({ request }) => {
        const body = (await request.json()) as { state: unknown };
        saved.push(body.state);
        return HttpResponse.json(body);
      }),
    );
    renderApp(`/projects/${id}`);
    const tools = await screen.findByRole('toolbar', { name: 'Поиск и фильтры' });
    expect(
      within(tools)
        .getByRole('button', { name: /Мои ветки/ })
        .getAttribute('aria-pressed'),
    ).toBe('false');
    expect(within(tools).getByRole('button', { name: /Самопроверка/ })).toBeTruthy();
    const grid = screen.getByRole('treegrid');
    await within(grid).findByText('Фронтенд');

    fireEvent.change(within(tools).getByRole('searchbox'), { target: { value: '1с' } });
    await waitFor(() => expect(grid.querySelector('mark')?.textContent).toBe('1С'));
    expect(within(grid).queryByText('Фронтенд')).toBeNull();
    fireEvent.change(within(tools).getByRole('searchbox'), { target: { value: '' } });

    fireEvent.click(within(tools).getByRole('button', { name: 'до фаз' }));
    await waitFor(() => expect(within(grid).queryByText('Бэкенд')).toBeNull());
    fireEvent.click(within(tools).getByRole('button', { name: 'всё раскрыть' }));
    await within(grid).findByText('Бэкенд');

    fireEvent.click(within(tools).getByRole('button', { name: /С вопросами/ }));
    await waitFor(() => expect(saved.at(-1)).toMatchObject({ filters: ['questions'], collapsed: [] }), {
      timeout: 2000,
    });
  });

  it('сохранённые фильтры восстанавливаются, «Риски» из верхней полосы включает чип', async () => {
    persona.current = PERSONAS.moderator;
    server.use(
      http.get(api('/me/view-state/:id'), () =>
        HttpResponse.json({ state: { filters: ['questions'], collapsed: [] } }),
      ),
    );
    renderApp(`/projects/${id}`);
    const tools = await screen.findByRole('toolbar', { name: 'Поиск и фильтры' });
    expect(
      within(tools)
        .getByRole('button', { name: /С вопросами/ })
        .getAttribute('aria-pressed'),
    ).toBe('true');
    const bar = screen.getByRole('banner', { name: 'Проект' });
    fireEvent.click(within(bar).getByRole('button', { name: /Риски/ }));
    expect(within(tools).getByRole('button', { name: /Риски/ }).getAttribute('aria-pressed')).toBe('true');
  });
});
