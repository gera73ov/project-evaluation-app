/** FE-042 · вкладки статистики 11.10: доли, объёмы, кандидаты, допущения и риски, снимки. */
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import type { components } from '../../../shared/api/client';
import { D } from '../../../shared/calc/decimal';
import { PROJECTS } from '../../../shared/api/mocks/data';
import { PERSONAS } from '../../../shared/api/mocks/personas';
import { persona } from '../../../test/setup';
import { renderApp } from '../../../test/render';
import { largeRows, shares, tagLines, volumeRows, volumeSummary } from './details';
import { toggleSelection } from './SnapshotsPage';

type Project = components['schemas']['Project'];
type Stats = components['schemas']['Stats'];
type Node = components['schemas']['Node'];

const node = (n: Record<string, unknown> & { id: string }) =>
  ({
    parent_id: null,
    kind: 'item',
    type_id: null,
    discipline_id: null,
    phase_id: null,
    title: n.id,
    multiplier: 1,
    e: null,
    o: null,
    r: null,
    p: null,
    ...n,
  }) as unknown as Node;

const project = {
  disciplines: [
    { discipline_id: 'a', name: 'Аналитика' },
    { discipline_id: 'b', name: 'Бэкенд' },
    { discipline_id: 'q', name: 'QA' },
  ],
} as unknown as Project;

const nodes = [
  node({ id: 'ph1', kind: 'phase', phase_id: 'f1' }),
  node({ id: 'da', kind: 'discipline', parent_id: 'ph1', discipline_id: 'a', phase_id: 'f1', e: '10' }),
  node({ id: 'db', kind: 'discipline', parent_id: 'ph1', discipline_id: 'b', phase_id: 'f1', e: '20' }),
  node({ id: 'ph2', kind: 'phase', phase_id: 'f2' }),
  node({ id: 'db2', kind: 'discipline', parent_id: 'ph2', discipline_id: 'b', phase_id: 'f2', e: '40' }),
  node({ id: 'g', parent_id: 'db', title: 'Модуль', type_id: 'mod', discipline_id: 'b', e: '20' }),
  node({ id: 's1', parent_id: 'g', title: 'Экран 1', type_id: 'scr', discipline_id: 'b', e: '12', multiplier: 3 }),
  node({ id: 's2', parent_id: 'g', title: 'Экран 2', type_id: 'scr', discipline_id: 'a', e: '8' }),
  node({ id: 'w', parent_id: 'db2', title: 'Работа', type_id: 'wrk', discipline_id: 'b', e: '40' }),
];

describe('правила вкладок', () => {
  it('доли: все фазы и одна фаза, дисциплины без часов скрыты', () => {
    expect(shares(project, nodes, null).map((s) => [s.name, s.pct])).toEqual([
      ['Аналитика', 14],
      ['Бэкенд', 86],
    ]);
    expect(shares(project, nodes, 'f2').map((s) => [s.name, s.pct])).toEqual([['Бэкенд', 100]]);
  });

  it('объёмы: E и дисциплины по листьям, у «Работы» нет E на единицу; сводка без «Работы»', () => {
    const stats = {
      volumes: [
        { type_id: 'scr', name: 'Экран', count: 4 },
        { type_id: 'wrk', name: 'Работа', count: 1 },
      ],
    } as unknown as Stats;
    const rows = volumeRows(stats, nodes, project, (id) => id === 'wrk');
    expect(rows.map((r) => [r.name, r.e, r.eUnit, r.disciplines])).toEqual([
      ['Работа', '40', null, ['Бэкенд']],
      ['Экран', '20', '5', ['Бэкенд', 'Аналитика']],
    ]);
    expect(volumeSummary(rows)).toBe('Экран — 4');
  });

  it('крупные листья: выше порога и повторяющийся; без порога пометок нет', () => {
    const stats = {
      candidates: {
        large: [
          { node_id: 'w', e: '40', e_unit: '40.00', repeating: false },
          { node_id: 's1', e: '12', e_unit: '4.00', repeating: true },
          { node_id: 'gone', e: '1', e_unit: '1.00', repeating: false },
        ],
        wide_fork: [],
      },
    } as unknown as Stats;
    const rows = largeRows(stats, nodes, new D(16));
    expect(rows.map((r) => [r.title, r.mark])).toEqual([
      ['Работа', 'above'],
      ['Экран 1', 'repeating'],
    ]);
    expect(rows[1]?.path).toBe('ph1 › db › Модуль');
    expect(largeRows(stats, nodes, null).at(0)?.mark).toBeNull();
  });

  it('метки: порядок категорий, строка УП — среди допущений', () => {
    const item = (text: string) => ({ node_id: 'n', tag_id: text, text, path: ['A', 'B'] });
    const stats = {
      tag_lists: [
        { category: 'risk', items: [item('риск')] },
        { category: 'assumption', items: [item('допущение')] },
      ],
    } as unknown as Stats;
    const lines = tagLines(stats, { pct: '15', reason: 'обычный проект' }, 'Настройки');
    expect(lines.map((l) => [l.category, l.text])).toEqual([
      ['assumption', 'допущение'],
      ['assumption', 'УП 15%: обычный проект'],
      ['risk', 'риск'],
    ]);
    expect(lines.at(1)?.nodeId).toBeNull();
    expect(tagLines(stats, { pct: '15', reason: ' ' }, 'Настройки')).toHaveLength(2);
  });

  it('выбор снимков: не больше двух, третий вытесняет первый', () => {
    expect(toggleSelection([], 'a')).toEqual(['a']);
    expect(toggleSelection(['a', 'b'], 'c')).toEqual(['b', 'c']);
    expect(toggleSelection(['a', 'b'], 'a')).toEqual(['b']);
  });
});

const portal = PROJECTS.portal;

function open(tab: string, who: 'expert' | 'moderator' = 'moderator') {
  persona.current = who === 'expert' ? PERSONAS.expert : PERSONAS.moderator;
  renderApp(`/projects/${portal.id}/stats/${tab}`);
}

describe('вкладки на демо-проекте', () => {
  it('доли: дисциплины с процентами и выбор фазы', async () => {
    open('shares');
    const card = (await screen.findByRole('heading', { name: 'Доли дисциплин в работах' })).closest(
      'section',
    ) as HTMLElement;
    await waitFor(() => expect(within(card).getAllByText(/\d+%/).length).toBeGreaterThan(1));
    expect(screen.getByRole('textbox', { name: 'Фаза' })).toBeTruthy();
  });

  it('объёмы: таблица типов и сводка для КП', async () => {
    open('volumes');
    expect(await screen.findByRole('heading', { name: 'Сколько чего оцениваем' })).toBeTruthy();
    expect(await screen.findByText(/Сводка для КП/)).toBeTruthy();
  });

  it('кандидаты: клик по листу открывает его на рабочем экране', async () => {
    open('candidates');
    const card = (await screen.findByRole('heading', { name: /Крупные листья/ })).closest('section') as HTMLElement;
    const first = (await within(card).findAllByRole('button')).at(0) as HTMLElement;
    fireEvent.click(first);
    await waitFor(() => expect(window.location.pathname).toBe(`/projects/${portal.id}`));
    expect(new URLSearchParams(window.location.search).get('node')).toBeTruthy();
  });

  it('допущения и риски: строки макета; Word — только с правом выгрузки с деньгами', async () => {
    open('tags');
    expect(await screen.findByText(/Спецификация 1С появится не раньше декабря/)).toBeTruthy();
    expect(screen.getByRole('button', { name: /Word/ })).toBeTruthy();
  });

  it('эксперт: без Word', async () => {
    open('tags', 'expert');
    expect(await screen.findByText(/может не поддерживать нужные scopes/)).toBeTruthy();
    expect(screen.queryByRole('button', { name: /Word/ })).toBeNull();
  });

  it('снимки: ошибочный не выбирается, два выбранных — «Сравнить два»', async () => {
    open('snapshots');
    const invalid = await screen.findByRole('checkbox', { name: /черновик/ });
    expect((invalid as HTMLInputElement).disabled).toBe(true);
    expect(screen.getByText('ошибочный')).toBeTruthy();
    expect(screen.getByText(/В КП, USD/)).toBeTruthy();
    const two = screen.getByRole('button', { name: 'Сравнить два' }) as HTMLButtonElement;
    expect(two.disabled).toBe(true);
    fireEvent.click(screen.getByRole('checkbox', { name: /v1/ }));
    expect((screen.getByRole('button', { name: 'Сравнить с текущим' }) as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(screen.getByRole('checkbox', { name: /v2/ }));
    expect(two.disabled).toBe(false);
    fireEvent.click(two);
    await waitFor(() => expect(window.location.pathname).toBe(`/projects/${portal.id}/stats/compare`));
    const q = new URLSearchParams(window.location.search);
    expect([q.get('a'), q.get('b')].every(Boolean)).toBe(true);
  });

  it('эксперт: снимки без денег', async () => {
    open('snapshots', 'expert');
    expect(await screen.findByRole('checkbox', { name: /v1/ })).toBeTruthy();
    expect(screen.queryByText(/В КП/)).toBeNull();
  });
});
