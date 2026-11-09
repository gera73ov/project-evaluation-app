/** FE-040 · сетка готовности (11.8): ячейки и флажки, «Стоимость» только с деньгами, переход к ветке, напоминание. */
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import type { components } from '../../../shared/api/client';
import { PROJECTS } from '../../../shared/api/mocks/data';
import { PERSONAS } from '../../../shared/api/mocks/personas';
import { persona } from '../../../test/setup';
import { renderApp } from '../../../test/render';
import { buildGrid, cellKey, ratioScale, remindState } from './readiness';

type Project = components['schemas']['Project'];
type Stats = components['schemas']['Stats'];
type Tree = components['schemas']['Tree'];

const portal = PROJECTS.portal;

describe('правила сетки', () => {
  const project = {
    phases: [
      { phase_id: 'f1', name: 'Анализ', is_enabled: true },
      { phase_id: 'pm', name: 'Управление проектом', is_enabled: true },
      { phase_id: 'off', name: 'Выключена', is_enabled: false },
    ],
    disciplines: [
      { discipline_id: 'a', name: 'Аналитика', has_expert: true },
      { discipline_id: 'd', name: 'DevOps', has_expert: false },
    ],
  } as unknown as Project;
  const stats = {
    readiness: [
      {
        phase_id: 'f1',
        discipline_id: 'a',
        e: '83.3',
        status: 'done',
        last_change_at: '2026-11-01T10:00:00Z',
        flags: ['large', 'overdue'],
        overdue_working_days: 2,
      },
      {
        phase_id: 'f1',
        discipline_id: 'd',
        e: '0',
        status: 'not_started',
        last_change_at: null,
        flags: [],
        overdue_working_days: null,
      },
    ],
  } as unknown as Stats;
  const tree = {
    branch_statuses: [
      {
        phase_id: 'f1',
        discipline_id: 'a',
        status: 'done',
        changed_by: { full_name: 'О. Кузнецова' },
        changed_at: '2026-11-01T10:00:00Z',
        open_questions: 2,
        has_expert: true,
      },
    ],
    nodes: [{ id: 'n-a', kind: 'discipline', phase_id: 'f1', discipline_id: 'a', unaccounted_leaves: 3 }],
  } as unknown as Tree;

  it('фазы только с ветками; данные ячейки из статистики и дерева', () => {
    const grid = buildGrid(project, stats, tree);
    expect(grid.phases.map((p) => p.id)).toEqual(['f1']);
    expect(grid.cells.get(cellKey('f1', 'a'))).toMatchObject({
      nodeId: 'n-a',
      status: 'done',
      who: 'О. Кузнецова',
      large: true,
      questions: 2,
      unaccounted: 3,
      overdueDays: 2,
      noExpert: false,
    });
    expect(grid.cells.get(cellKey('f1', 'd'))).toMatchObject({ status: 'not_started', noExpert: true });
  });

  it('напомнить некому, если у «не начато» нет эксперта', () => {
    expect(remindState(buildGrid(project, stats, tree))).toEqual({ canRemind: false, withoutExpert: ['DevOps'] });
  });

  it('шкала соотношения: норма 25–35 → 0…50%', () => {
    expect(ratioScale(35)).toBe(50);
    expect(ratioScale(60)).toBe(90);
  });
});

async function openStats(who: 'expert' | 'moderator') {
  persona.current = who === 'expert' ? PERSONAS.expert : PERSONAS.moderator;
  renderApp(`/projects/${portal.id}/stats`);
  return screen.findByRole('table', { name: /Сетка готовности/ });
}

describe('вкладка «Готовность»', () => {
  it('модератор: строка «Стоимость», деньги в итоге, соотношение ниже нормы', async () => {
    const grid = await openStats('moderator');
    expect(await within(grid).findByText(/Стоимость, ₽/)).toBeTruthy();
    expect(screen.getByText(/Итог без НДС, ₽/)).toBeTruthy();
    expect(await screen.findByText('QA к (Бэкенд + Фронтенд)')).toBeTruthy();
    expect(screen.getByText(/ниже нормы на 1 п\.п\./)).toBeTruthy();
    expect(screen.getByRole('button', { name: /Напомнить не начавшим/ })).toBeTruthy();
  });

  it('эксперт: без «Стоимости» и денег в DOM, без напоминания', async () => {
    const grid = await openStats('expert');
    await within(grid).findByText('92,7');
    expect(document.body.textContent).not.toContain('Стоимость');
    expect(document.body.textContent).not.toContain('НДС');
    expect(screen.queryByRole('button', { name: /Напомнить не начавшим/ })).toBeNull();
    expect(screen.getByText('Проверено ревьюерами')).toBeTruthy();
  });

  it('клик по ячейке ведёт на рабочий экран с веткой', async () => {
    const grid = await openStats('expert');
    fireEvent.click((await within(grid).findByText('92,7')).closest('button') as HTMLElement);
    await waitFor(() => expect(window.location.pathname).toBe(`/projects/${portal.id}`));
    expect(new URLSearchParams(window.location.search).get('node')).toBeTruthy();
  });
});
