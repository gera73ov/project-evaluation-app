/** FE-050 · портфель руководителя пресейла (11.13): показатели, полосы, «договор / в КП», реестр, «Стать модератором», Excel. */
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { PROJECTS } from '../../shared/api/mocks/data';
import { PERSONAS } from '../../shared/api/mocks/personas';
import { persona, server } from '../../test/setup';
import { renderApp } from '../../test/render';
import {
  contractRatios,
  defaultPeriod,
  joinState,
  kpis,
  monthBars,
  type PortfolioItem,
  type PortfolioSummary,
} from './portfolio';

const summary = {
  period: { from: '2026-07-01', to: '2026-11-03' },
  by_status: { estimation: 5, consolidation: 2, completed: 15, archived: 2 },
  by_outcome: { won: 6, lost: 7, cancelled: 2, unknown: 9 },
  won_share_count_pct: '46.2',
  won_share_money_pct: '52.2',
  sum_won_cur: '31400000',
  sum_lost_cur: '28700000',
  sum_in_progress_cur: '18200000',
  loss_reasons: [],
  contract_to_quote_median_pct: '93',
  by_month: [{ month: '2026-07', won: 2, lost: 2, cancelled: 0 }],
  first_snapshot_median_days: null,
} as unknown as PortfolioSummary;

const item = (over: Partial<PortfolioItem>) =>
  ({
    id: 'p',
    name: 'Проект',
    moderators: [],
    status: 'estimation',
    outcome: 'unknown',
    created_at: '2026-07-10T10:00:00Z',
    updated_at: '2026-10-01T10:00:00Z',
    money: { contract_amount: null, quote_cur: '100' },
    ...over,
  }) as unknown as PortfolioItem;

describe('правила портфеля', () => {
  it('период по умолчанию — с 1-го числа четыре месяца назад', () => {
    expect(defaultPeriod(new Date('2026-11-03T09:00:00Z'))).toEqual({ from: '2026-07-01', to: '2026-11-03' });
  });

  it('«сегодня» — в поясе пользователя: после полуночи по Москве уже следующий день', () => {
    const lateUtc = new Date('2026-11-30T21:30:00Z');
    expect(defaultPeriod(lateUtc, 'UTC')).toEqual({ from: '2026-07-01', to: '2026-11-30' });
    expect(defaultPeriod(lateUtc, 'Europe/Moscow')).toEqual({ from: '2026-08-01', to: '2026-12-01' });
  });

  it('показатели: проекты по статусам, «6 из 13», договор / в КП как отношение', () => {
    expect(kpis(summary)).toMatchObject({
      total: 24,
      inWork: 7,
      completed: 15,
      archived: 2,
      won: 6,
      decided: 13,
      cancelled: 2,
      unknown: 9,
      contractRatio: '0.93',
      discountPct: '7',
      decidedRub: '60100000',
    });
  });

  it('полоса месяца: без итога — из реестра периода', () => {
    const items = [1, 2, 3, 4, 5].map((n) => item({ id: String(n) }));
    expect(monthBars(summary, items)).toEqual([{ month: '2026-07', won: 2, lost: 2, none: 1, total: 5 }]);
  });

  it('договор / в КП — только выигранные с суммой, свежие сверху', () => {
    const won = (id: string, at: string, contract: string | null) =>
      item({ id, outcome: 'won', updated_at: at, money: { contract_amount: contract, quote_cur: '200' } as never });
    expect(
      contractRatios([won('a', '2026-10-01', '190'), won('b', '2026-10-05', '200'), won('c', '2026-10-09', null)]),
    ).toEqual([
      { id: 'b', name: 'Проект', ratio: '1' },
      { id: 'a', name: 'Проект', ratio: '0.95' },
    ]);
  });

  it('«Стать модератором»: скрыта, если уже модератор; в архиве неактивна', () => {
    const me = { id: 'me', full_name: 'Я' } as PortfolioItem['moderators'][number];
    expect(joinState(item({ moderators: [me] }), 'me')).toBe('hidden');
    expect(joinState(item({ status: 'archived' }), 'me')).toBe('archived');
    expect(joinState(item({}), 'me')).toBe('available');
  });
});

const posts: string[] = [];
beforeEach(() => {
  server.events.on('request:start', ({ request }) => {
    if (request.method === 'POST') posts.push(new URL(request.url).pathname);
  });
});
afterEach(() => {
  server.events.removeAllListeners();
  posts.length = 0;
  vi.useRealTimers();
});

async function openPortfolio() {
  persona.current = PERSONAS.presale_head;
  renderApp('/portfolio');
  return screen.findByRole('table');
}

const rowOf = (table: HTMLElement, name: string) => within(table).getByText(name).closest('tr') as HTMLElement;

describe('экран «Портфель»', () => {
  it('показатели, диаграммы и реестр с деньгами', async () => {
    const table = await openPortfolio();
    expect(await screen.findByText('Проектов за период')).toBeTruthy();
    expect(screen.getByText('4 из 7')).toBeTruthy();
    expect(screen.getByText('Результаты по месяцам')).toBeTruthy();
    expect(screen.getByText(/Договор к «в КП» по выигранным/)).toBeTruthy();
    const portal = rowOf(table, PROJECTS.portal.name);
    expect(within(portal).getByText('P80')).toBeTruthy();
    expect(within(portal).getByText(/USD/)).toBeTruthy();
    const orphan = rowOf(table, 'Чат-бот поддержки');
    expect(orphan.className).toContain('muted');
    expect(within(orphan).getByText('нет модератора')).toBeTruthy();
    expect(within(orphan).getByText('не заданы ставки')).toBeTruthy();
    expect(screen.getByText(/Справочно: медиана/)).toBeTruthy();
  });

  it('«Другое» в причинах проигрыша раскрывает тексты', async () => {
    await openPortfolio();
    fireEvent.click(await screen.findByRole('button', { name: 'Другое' }));
    expect(screen.getByText('«Заказчик заморозил бюджет до весны»')).toBeTruthy();
  });

  it('фильтр результата сужает реестр', async () => {
    await openPortfolio();
    fireEvent.click(screen.getByRole('textbox', { name: 'Результат' }));
    fireEvent.click(await screen.findByRole('option', { name: 'Результат: выигран' }));
    await waitFor(() => expect(within(screen.getByRole('table')).queryByText('Мобильный банк')).toBeNull());
    expect(within(screen.getByRole('table')).getByText('CRM для агентства')).toBeTruthy();
  });

  it('«Стать модератором»: в архиве неактивна, иначе добавляет себя', async () => {
    const table = await openPortfolio();
    const archived = rowOf(table, 'Учёт оборудования');
    expect((within(archived).getByRole('button', { name: /Стать модератором/ }) as HTMLButtonElement).disabled).toBe(
      true,
    );
    expect(within(archived).getByText('Сначала восстановите проект')).toBeTruthy();
    fireEvent.click(within(rowOf(table, 'Чат-бот поддержки')).getByRole('button', { name: /Стать модератором/ }));
    expect(await screen.findByRole('status')).toBeTruthy();
    expect(screen.getByRole('status').textContent).toContain('Вы модератор проекта «Чат-бот поддержки»');
    expect(posts.some((p) => p.endsWith('/join-as-moderator'))).toBe(true);
    const fresh = () => rowOf(screen.getByRole('table'), 'Чат-бот поддержки');
    await waitFor(() => expect(within(fresh()).queryByRole('button', { name: /Стать модератором/ })).toBeNull());
    expect(within(fresh()).queryByText('нет модератора')).toBeNull();
  });

  it('⇩ Excel: задание выгрузки, ожидание и файл', async () => {
    const created = vi.fn(() => 'blob:x');
    Object.assign(URL, { createObjectURL: created, revokeObjectURL: vi.fn() });
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined);
    await openPortfolio();
    fireEvent.click(screen.getByRole('button', { name: /Excel/ }));
    await waitFor(() => expect(created).toHaveBeenCalled(), { timeout: 5000 });
    expect(posts).toContain('/api/v1/portfolio/export');
    expect(click).toHaveBeenCalled();
    click.mockRestore();
  });
});
