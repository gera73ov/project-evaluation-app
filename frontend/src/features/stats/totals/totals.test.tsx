/** FE-041 · «Итоги» (11.9): строки по фазам и дисциплинам, деньги только с правом, график, Excel. */
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { components } from '../../../shared/api/client';
import { PROJECTS } from '../../../shared/api/mocks/data';
import { PERSONAS } from '../../../shared/api/mocks/personas';
import { persona, server } from '../../../test/setup';
import { renderApp } from '../../../test/render';
import { disciplineRows, niceScale, phaseRows, pmBasePhases, sumCosts } from './totals';

type Project = components['schemas']['Project'];
type Stats = components['schemas']['Stats'];

const h = (e: string) => ({ e, sigma: '1', p80: e, p90: e });
const project = {
  phases: [
    { phase_id: 'f1', name: 'Анализ', is_enabled: true, in_pm_base: true },
    { phase_id: 'f2', name: 'Разработка', is_enabled: true, in_pm_base: true },
    { phase_id: 'pm', name: 'Управление проектом', is_enabled: true, in_pm_base: false },
    { phase_id: 'off', name: 'Выключена', is_enabled: false, in_pm_base: true },
  ],
  disciplines: [
    { discipline_id: 'a', name: 'Аналитика' },
    { discipline_id: 'd', name: 'DevOps' },
  ],
} as unknown as Project;
const stats = {
  totals: {
    by_phase: [
      { phase_id: 'f1', hours: h('25'), share_pct: null },
      { phase_id: 'f2', hours: h('55'), share_pct: null },
    ],
    by_discipline: [
      { discipline_id: 'a', hours: h('80'), share_pct: null },
      { discipline_id: 'd', hours: h('0'), share_pct: null },
    ],
    works: h('80'),
    pm: h('20'),
    total: h('100'),
    quote_figure: 'p80',
    duration_weeks: 4,
  },
  money: {
    cost_by_phase: [{ phase_id: 'f1', cost_rub: '75000' }],
    cost_by_discipline: [
      { discipline_id: 'a', cost_rub: '240000' },
      { discipline_id: 'd', cost_rub: null },
    ],
  },
} as unknown as Stats;

describe('правила вкладки', () => {
  it('фазы: только включённые с часами, доля — от итога', () => {
    expect(phaseRows(project, stats).map((r) => [r.name, r.share, r.cost])).toEqual([
      ['Анализ', '25', '75000'],
      ['Разработка', '55', null],
    ]);
    expect(pmBasePhases(project)).toBe(2);
  });

  it('дисциплина без часов — серая строка; «Работы» в деньгах — сумма строк', () => {
    const rows = disciplineRows(project, stats);
    expect(rows.map((r) => [r.name, r.hours === null, r.share])).toEqual([
      ['Аналитика', false, '100'],
      ['DevOps', true, null],
    ]);
    expect(sumCosts(rows)).toBe('240000');
    expect(sumCosts([])).toBeNull();
  });

  it('шкала графика — круглый шаг', () => {
    expect(niceScale(425.5)).toEqual({ top: 450, step: 150 });
    expect(niceScale(0)).toEqual({ top: 1, step: 1 });
  });
});

const portal = PROJECTS.portal;

async function openTotals(who: 'expert' | 'moderator') {
  persona.current = who === 'expert' ? PERSONAS.expert : PERSONAS.moderator;
  renderApp(`/projects/${portal.id}/stats/totals`);
  return screen.findByRole('heading', { name: 'По фазам' });
}

afterEach(() => {
  server.events.removeAllListeners();
});

describe('вкладка «Итоги»', () => {
  it('модератор: стоимость, ставки, «Сумма для КП» с выделенной P80 и курсом', async () => {
    await openTotals('moderator');
    expect(await screen.findByRole('heading', { name: /Сумма для КП/ })).toBeTruthy();
    const quote = screen.getByRole('heading', { name: /Сумма для КП/ }).closest('section') as HTMLElement;
    expect(within(quote).getByText(/USD, курс 92,5000/)).toBeTruthy();
    expect(within(quote).getByText('P80 · в КП').className).toContain('on');
    expect(within(quote).getByText('Без НДС, USD')).toBeTruthy();
    const phases = screen.getByRole('heading', { name: 'По фазам' }).closest('section') as HTMLElement;
    expect(within(phases).getByText(/Стоимость, ₽/)).toBeTruthy();
    expect(within(phases).getByText(/от базы: 3 фазы/)).toBeTruthy();
    expect(await screen.findAllByText(/Ставка/)).toBeTruthy();
    expect(screen.getByRole('button', { name: /Excel/ })).toBeTruthy();
  });

  it('эксперт: без денег в DOM; график с отметками снимков', async () => {
    await openTotals('expert');
    const chart = await screen.findByRole('img', { name: 'Динамика итога' });
    expect(document.body.textContent).not.toContain('Стоимость');
    expect(document.body.textContent).not.toContain('Сумма для КП');
    expect(document.body.textContent).not.toContain('НДС');
    expect(screen.queryByRole('radio', { name: /USD/ })).toBeNull();
    await waitFor(() => expect(within(chart).getByText(/v1 — КП отправлено/)).toBeTruthy());
    // те же точки в скрытой таблице: 8 дней
    const table = screen.getByRole('table', { name: 'Динамика итога' });
    expect(within(table).getAllByRole('row')).toHaveLength(9);
  });

  it('«% работ» показывает доли дисциплин', async () => {
    await openTotals('expert');
    fireEvent.click(screen.getByRole('radio', { name: '% работ' }));
    const disc = screen.getByRole('heading', { name: 'По дисциплинам' }).closest('section') as HTMLElement;
    expect(within(disc).getByText('E, %')).toBeTruthy();
    expect(within(disc).queryAllByText('100,0%').length).toBe(0);
    expect(within(disc).getAllByText('100%').length).toBeGreaterThan(0);
  });

  it('модератор: график в валюте КП', async () => {
    await openTotals('moderator');
    fireEvent.click(await screen.findByRole('radio', { name: /USD/ }));
    const table = await screen.findByRole('table', { name: 'Динамика итога' });
    expect(within(table).getByText('в КП, USD')).toBeTruthy();
  });

  it('⇩ Excel: задание выгрузки вкладки и файл', async () => {
    const created = vi.fn(() => 'blob:x');
    Object.assign(URL, { createObjectURL: created, revokeObjectURL: vi.fn() });
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined);
    const paths: string[] = [];
    server.events.on('request:start', ({ request }) => paths.push(new URL(request.url).pathname));
    await openTotals('moderator');
    fireEvent.click(screen.getByRole('button', { name: /Excel/ }));
    await waitFor(() => expect(created).toHaveBeenCalled(), { timeout: 5000 });
    expect(paths).toContain(`/api/v1/projects/${portal.id}/stats/totals/export`);
    click.mockRestore();
  });
});
