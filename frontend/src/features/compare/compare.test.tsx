/** FE-044 · сравнение со снимком (11.12): стороны, сводка, деньги только с правом, фильтры, экспорт. */
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { components } from '../../shared/api/client';
import { PROJECTS } from '../../shared/api/mocks/data';
import { uuidFrom } from '../../shared/api/mocks/ids';
import { PERSONAS } from '../../shared/api/mocks/personas';
import { persona, server } from '../../test/setup';
import { renderApp } from '../../test/render';
import { compareHref, countByFilter, deltaPct, deltaTone, forkOf, orderPair, sidesOf } from './compare';

type Diff = components['schemas']['Diff'];

describe('правила сравнения', () => {
  it('стороны из адреса: без b — текущее состояние', () => {
    expect(sidesOf('s1', null)).toEqual({ left: 'current', right: 's1' });
    expect(sidesOf('s1', 's2')).toEqual({ left: 's2', right: 's1' });
    expect(sidesOf(null, 's2')).toBeNull();
    expect(compareHref('p', 'current', 's1')).toBe('/projects/p/stats/compare?a=s1');
    expect(compareHref('p', 's2', 's1')).toBe('/projects/p/stats/compare?a=s1&b=s2');
  });

  it('из двух снимков «было» — более ранний', () => {
    const x = { id: 'x', created_at: '2026-11-03T10:00:00Z' };
    const y = { id: 'y', created_at: '2026-11-01T10:00:00Z' };
    expect(orderPair(x, y)).toEqual({ older: y, newer: x });
  });

  it('процент разницы, числа на фильтрах, вилка и цвет разницы', () => {
    expect(deltaPct('378.2', '28.3')).toBe(7.5);
    expect(deltaPct('0', '5')).toBeNull();
    const diff = {
      rows: [{ change: 'changed' }, { change: 'added' }, { change: 'changed' }],
      params: [{ key: 'exchange_rate' }],
    } as unknown as Diff;
    const counts = countByFilter(diff.rows, diff.params);
    expect([counts.get('all'), counts.get('changed'), counts.get('removed'), counts.get('params')]).toEqual([
      4, 2, 0, 1,
    ]);
    expect(forkOf({ o: '30', r: '40', p: '60', multiplier: 1, e: '41.67' } as never)).toBe('30–40–60');
    expect(forkOf({ o: '1', r: '2.5', p: '4', multiplier: 3, e: '7.50' } as never)).toBe('1–2,5–4 × 3');
    expect(forkOf(null)).toBeNull();
    expect([deltaTone('1'), deltaTone('-1'), deltaTone('0')]).toEqual(['bad', 'ok', null]);
  });
});

const portal = PROJECTS.portal;
const v1 = uuidFrom('snapshot', 'portal', 'v1');
const v2 = uuidFrom('snapshot', 'portal', 'v2');

function open(who: 'expert' | 'moderator', query = `a=${v1}`) {
  persona.current = who === 'expert' ? PERSONAS.expert : PERSONAS.moderator;
  renderApp(`/projects/${portal.id}/stats/compare?${query}`);
  return screen.findByRole('table');
}

afterEach(() => {
  server.events.removeAllListeners();
});

describe('экран сравнения', () => {
  it('модератор: сводка, деньги «было → стало», строки O–R–P, параметр и пояснение про УП', async () => {
    const table = await open('moderator');
    const row = (title: string) =>
      within(table)
        .getAllByRole('row')
        .find((r) => r.textContent?.includes(title)) as HTMLElement;
    expect(row('Обмен с 1С').textContent).toContain('30–40–60 → 40–60–100');
    expect(row('Обмен с 1С').textContent).toContain('+21,7');
    expect(row('Обмен с 1С').textContent).toContain('И. Иванов ·');
    expect(row('Тесты обмена с 1С').textContent).toContain('— → 8–12–24');
    expect(row('Дашборд').textContent).toContain('−4,7');
    expect(row('Прототипы').textContent).toContain('4–6–10 → —');
    expect(row('Курс USD').textContent).toContain('90,0000 → 92,5000');
    expect(row('Курс USD').textContent).toContain('параметр 🔒');
    expect(screen.getByRole('region', { name: 'Итог E' }).textContent).toMatch(/→/);
    const rub = screen.getByRole('region', { name: 'Итог без НДС, ₽' });
    expect(rub.textContent).toMatch(/→/);
    expect(rub.textContent).toContain('ставки не менялись');
    expect(screen.getByRole('region', { name: 'Итог без НДС, USD' }).textContent).toMatch(
      /из них курс 90,0 → 92,5: [−-]/,
    );
    expect(screen.getByRole('button', { name: /Параметры\s*1/ })).toBeTruthy();
    expect(screen.getByText(/Управление проектом пересчитано автоматически: 18% от работ/)).toBeTruthy();
    expect((screen.getByRole('textbox', { name: 'Что сравниваем' }) as HTMLInputElement).value).toBe(
      'Текущее состояние',
    );
  });

  it('эксперт: денег нет в DOM', async () => {
    await open('expert');
    expect(document.body.textContent).not.toContain('НДС');
    expect(document.body.textContent).not.toContain('₽');
    expect(document.body.textContent).not.toContain('Курс USD');
    expect(screen.getByRole('button', { name: /Параметры\s*0/ })).toBeTruthy();
  });

  it('фильтр по виду изменения', async () => {
    await open('expert');
    fireEvent.click(screen.getByRole('button', { name: /Добавлены\s*1/ }));
    const rows = within(screen.getByRole('table')).getAllByRole('row');
    expect(rows).toHaveLength(2);
    expect(rows.at(1)?.textContent).toContain('Тесты обмена с 1С');
    fireEvent.click(screen.getByRole('button', { name: /Перемещены\s*0/ }));
    expect(await screen.findByText('Изменений этого вида нет')).toBeTruthy();
  });

  it('два снимка: запрос diff с правым снимком и with = левый', async () => {
    const urls: string[] = [];
    server.events.on('request:start', ({ request }) => urls.push(request.url));
    await open('expert', `a=${v1}&b=${v2}`);
    const diff = urls.map((u) => new URL(u)).find((u) => u.pathname.endsWith('/diff'));
    expect(diff?.pathname).toBe(`/api/v1/snapshots/${v1}/diff`);
    expect(diff?.searchParams.get('with')).toBe(v2);
  });

  it('экспорт сравнения в Excel', async () => {
    Object.assign(URL, { createObjectURL: vi.fn(() => 'blob:x'), revokeObjectURL: vi.fn() });
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined);
    const paths: string[] = [];
    server.events.on('request:start', ({ request }) => paths.push(new URL(request.url).pathname));
    await open('moderator');
    fireEvent.click(screen.getByRole('button', { name: 'Экспорт сравнения в Excel' }));
    await waitFor(() => expect(paths).toContain(`/api/v1/snapshots/${v1}/diff/export`));
    await waitFor(() => expect(click).toHaveBeenCalled(), { timeout: 5000 });
    click.mockRestore();
  });

  it('без снимка — подсказка выбрать снимок', async () => {
    persona.current = PERSONAS.expert;
    renderApp(`/projects/${portal.id}/stats/compare`);
    expect(await screen.findByText(/Выберите снимок для сравнения/)).toBeTruthy();
  });
});
