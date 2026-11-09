/** FE-014 · «Деньги» (11.6 №7–9, №13–14): нет блока у эксперта, TOTP_REQUIRED, сохранение ставки и курса. */
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { PROJECTS } from '../../../shared/api/mocks/data';
import { PERSONAS } from '../../../shared/api/mocks/personas';
import { persona, server } from '../../../test/setup';
import { HttpResponse, api, http, problem, renderApp } from '../../../test/render';
import { parseExchangeRate, parseRub, vatOptions } from './MoneySection';

const id = PROJECTS.portal.id;

function capturePut() {
  const bodies: Record<string, unknown>[] = [];
  server.use(
    http.put(api('/projects/:id/money'), async ({ request }) => {
      bodies.push((await request.json()) as Record<string, unknown>);
      return HttpResponse.json({}, { status: 500 });
    }),
  );
  return bodies;
}

async function openMoney() {
  renderApp(`/projects/${id}/settings`);
  const section = await screen.findByRole('region', { name: 'Деньги' });
  await within(section).findByText('Итог без НДС');
  return section;
}

describe('разбор полей «Деньги»', () => {
  it('курс: больше 0, до 4 знаков, запятая как разделитель', () => {
    expect(parseExchangeRate('92,5')).toBe('92.5000');
    expect(parseExchangeRate('0')).toBeNull();
    expect(parseExchangeRate('1.23456')).toBeNull();
    expect(parseExchangeRate('abc')).toBeNull();
  });

  it('ставка: пусто — не задана, целое до 1 000 000', () => {
    expect(parseRub('')).toBeNull();
    expect(parseRub('3 000')).toBe('3000');
    expect(parseRub('1000001')).toBeUndefined();
    expect(parseRub('12.5')).toBeUndefined();
  });
});

describe('настройки: «Деньги»', () => {
  it('у эксперта блока нет в разметке', async () => {
    persona.current = PERSONAS.expert;
    renderApp(`/projects/${id}/settings`);
    await screen.findByRole('region', { name: 'Команда' });
    expect(screen.queryByRole('region', { name: 'Деньги' })).toBeNull();
    expect(screen.queryByText(/₽/)).toBeNull();
  });

  it('без TOTP в сессии — «Подтвердите вход кодом» вместо сумм', async () => {
    persona.current = PERSONAS.moderator;
    server.use(http.get(api('/projects/:id/money'), () => problem(403, 'TOTP_REQUIRED')));
    renderApp(`/projects/${id}/settings`);
    const section = await screen.findByRole('region', { name: 'Деньги' });
    await within(section).findByText('🔒 Подтвердите вход кодом');
    expect(within(section).queryByText('Итог без НДС')).toBeNull();
  });

  it('ставка сохраняется при уходе фокуса: PUT со всеми ставками, остальные без изменений', async () => {
    persona.current = PERSONAS.moderator;
    const bodies = capturePut();
    const section = await openMoney();
    const qa = within(section).getByRole('textbox', { name: 'QA' });
    fireEvent.change(qa, { target: { value: '2 400' } });
    fireEvent.blur(qa);
    await waitFor(() => expect(bodies).toHaveLength(1));
    const rates = bodies[0]?.rates as {
      discipline_id: string | null;
      rate_rub: string | null;
    }[];
    expect(rates.filter((r) => r.rate_rub === '2400')).toHaveLength(1);
    expect(rates.find((r) => r.discipline_id === null)?.rate_rub).toBe('3200');
  });

  it('неверная ставка и курс — ошибка у поля, без запроса', async () => {
    persona.current = PERSONAS.moderator;
    const bodies = capturePut();
    const section = await openMoney();
    const qa = within(section).getByRole('textbox', { name: 'QA' });
    fireEvent.change(qa, { target: { value: '12,5' } });
    fireEvent.blur(qa);
    await within(section).findByText('Целое от 0 до 1 000 000');
    const rate = within(section).getByRole('textbox', { name: 'курс' });
    fireEvent.change(rate, { target: { value: '0' } });
    fireEvent.blur(rate);
    await within(section).findByText('Курс больше 0, до 4 знаков после запятой');
    expect(bodies).toHaveLength(0);
  });

  it('пресейл видит суммы, но не правит', async () => {
    persona.current = PERSONAS.presale;
    const section = await openMoney();
    expect(within(section).getByRole('textbox', { name: 'QA' }).hasAttribute('readonly')).toBe(true);
  });
});

describe('список ставок НДС', () => {
  it('текущая ставка проекта в списке, даже если её нет в справочнике', () => {
    const items = [
      { id: 'a', percent: '20', is_active: true },
      { id: 'b', percent: '10', is_active: false },
    ];
    expect(vatOptions(items, { vat_rate_id: 'a', vat_percent: null }).map((v) => v.id)).toEqual(['a']);
    expect(vatOptions(items, { vat_rate_id: 'b', vat_percent: null }).map((v) => v.id)).toEqual(['a', 'b']);
    expect(vatOptions([], { vat_rate_id: 'x', vat_percent: null })).toEqual([
      { id: 'x', percent: null, is_active: true },
    ]);
  });
});
