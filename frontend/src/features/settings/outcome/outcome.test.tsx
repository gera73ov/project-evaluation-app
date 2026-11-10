/** FE-016 · «Результат пресейла» (BR-PRJ-05): проверки, сумма только у ролей с деньгами, TOTP. */
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { PROJECTS } from '../../../shared/api/mocks/data';
import { LOSS_REASONS, putOutcome } from '../../../shared/api/mocks/demoOutcome';
import { PERSONAS } from '../../../shared/api/mocks/personas';
import { persona, server } from '../../../test/setup';
import { api, http, problem, renderApp } from '../../../test/render';
import { outcomeBody, parseAmount, validateDraft, type Draft } from './OutcomePage';

const portal = PROJECTS.portal;
const reasonId = (name: string) => LOSS_REASONS.find((r) => r.name === name)?.id ?? '';
const draft = (fields: Partial<Draft>): Draft => ({
  outcome: 'unknown',
  reasonId: null,
  reasonText: '',
  amount: '',
  ...fields,
});

describe('правила формы', () => {
  it('сумма: целое ≥ 0 любой длины, пробелы допустимы', () => {
    expect(parseAmount('1 500 000')).toBe('1500000');
    expect(parseAmount('')).toBeNull();
    expect(parseAmount('007')).toBe('7');
    expect(parseAmount('12345678901234567890')).toBe('12345678901234567890');
    expect(parseAmount('1,5')).toBeUndefined();
    expect(parseAmount('-1')).toBeUndefined();
  });

  it('причина обязательна при «проигран», текст — при «Другое»', () => {
    expect(validateDraft(draft({ outcome: 'lost' }), LOSS_REASONS, false)).toEqual({ reason: 'reasonRequired' });
    expect(validateDraft(draft({ outcome: 'lost', reasonId: reasonId('Другое') }), LOSS_REASONS, false)).toEqual({
      text: 'textRequired',
    });
    expect(validateDraft(draft({ outcome: 'lost', reasonId: reasonId('Цена') }), LOSS_REASONS, false)).toEqual({});
    expect(validateDraft(draft({ outcome: 'won', amount: 'abc' }), LOSS_REASONS, true)).toEqual({ amount: 'amount' });
    expect(validateDraft(draft({ outcome: 'won', amount: 'abc' }), LOSS_REASONS, false)).toEqual({});
  });

  it('тело: лишнее не уходит; сумма — только с правом на её правку', () => {
    const lost = draft({ outcome: 'lost', reasonId: reasonId('Цена'), reasonText: 'старое', amount: '5' });
    expect(outcomeBody(lost, LOSS_REASONS, true)).toEqual({
      outcome: 'lost',
      loss_reason_id: reasonId('Цена'),
      loss_reason_text: null,
      contract_amount: null,
    });
    expect(outcomeBody(draft({ outcome: 'won', amount: '1 000' }), LOSS_REASONS, false)).toEqual({
      outcome: 'won',
      loss_reason_id: null,
      loss_reason_text: null,
    });
  });
});

const calls: { method: string; body: unknown }[] = [];
afterEach(() => {
  server.events.removeAllListeners();
  calls.length = 0;
});

async function openOutcome(who: 'expert' | 'moderator' | 'presale' | 'presale_head') {
  persona.current = new Map(Object.entries(PERSONAS)).get(who) ?? PERSONAS.expert;
  server.events.on('request:start', ({ request }) => {
    if (request.method !== 'PUT') return;
    const entry = { method: request.method, body: null as unknown };
    calls.push(entry);
    void request
      .clone()
      .json()
      .then((b) => (entry.body = b))
      .catch(() => undefined);
  });
  renderApp(`/projects/${portal.id}/settings/outcome`);
  const section = await screen.findByRole('region', { name: 'Результат пресейла' });
  await within(section).findByText('Результат');
  return section;
}

const plain = (el: HTMLElement) => (el as HTMLInputElement).value.replace(/\s/g, ' ');
const pick = (section: HTMLElement, label: string) => fireEvent.click(within(section).getByLabelText(label));

describe('вкладка «Результат пресейла»', () => {
  it('у эксперта нет поля суммы и формы правки', async () => {
    putOutcome(portal, { outcome: 'won', contract_amount: '1500000' }, true);
    const section = await openOutcome('expert');
    await waitFor(() => expect((within(section).getByLabelText('выигран') as HTMLInputElement).checked).toBe(true));
    expect(within(section).queryByLabelText('Сумма договора')).toBeNull();
    expect(section.textContent?.replace(/\s/g, ' ')).not.toContain('1 500 000');
    expect(within(section).queryByRole('button', { name: 'Сохранить' })).toBeNull();
    expect(section.textContent).toContain('Только просмотр');
  });

  it('модератор: «проигран» без причины не сохраняется, «Другое» требует текст', async () => {
    const section = await openOutcome('moderator');
    pick(section, 'проигран');
    fireEvent.click(within(section).getByRole('button', { name: 'Сохранить' }));
    expect(await within(section).findByText('При «проигран» причина обязательна')).toBeTruthy();
    expect(calls).toHaveLength(0);
    fireEvent.click(within(section).getByRole('textbox', { name: 'Причина проигрыша' }));
    fireEvent.click(await within(section).findByRole('option', { name: 'Другое' }));
    expect(within(section).queryByRole('option', { name: 'Нет бюджета' })).toBeNull();
    expect(await within(section).findByText('Опишите причину')).toBeTruthy();
    fireEvent.change(within(section).getByRole('textbox', { name: 'Причина своими словами' }), {
      target: { value: 'Заказчик заморозил бюджет' },
    });
    fireEvent.click(within(section).getByRole('button', { name: 'Сохранить' }));
    await within(section).findByText('✓ сохранено');
    expect(calls.at(-1)?.body).toEqual({
      outcome: 'lost',
      loss_reason_id: reasonId('Другое'),
      loss_reason_text: 'Заказчик заморозил бюджет',
      contract_amount: null,
    });
  });

  it('модератор: «выигран» с суммой договора', async () => {
    const section = await openOutcome('moderator');
    pick(section, 'выигран');
    const amount = within(section).getByLabelText('Сумма договора');
    fireEvent.change(amount, { target: { value: '2500000' } });
    fireEvent.blur(amount);
    expect(plain(amount)).toBe('2 500 000');
    fireEvent.click(within(section).getByRole('button', { name: 'Сохранить' }));
    await within(section).findByText('✓ сохранено');
    expect(calls.at(-1)?.body).toEqual({
      outcome: 'won',
      loss_reason_id: null,
      loss_reason_text: null,
      contract_amount: '2500000',
    });
  });

  it('руководитель пресейла меняет и результат, и сумму договора (CR-015)', async () => {
    putOutcome(portal, { outcome: 'won', contract_amount: '1500000' }, true);
    const section = await openOutcome('presale_head');
    const amount = await within(section).findByLabelText('Сумма договора');
    expect(plain(amount)).toBe('1 500 000');
    expect((amount as HTMLInputElement).readOnly).toBe(false);
    fireEvent.change(amount, { target: { value: '1600000' } });
    fireEvent.click(within(section).getByRole('button', { name: 'Сохранить' }));
    await within(section).findByText('✓ сохранено');
    expect(calls.at(-1)?.body).toEqual({
      outcome: 'won',
      loss_reason_id: null,
      loss_reason_text: null,
      contract_amount: '1600000',
    });
  });

  it('сумма без TOTP в сессии — ввод кода вместо ошибки', async () => {
    server.use(http.put(api('/projects/:id/outcome'), () => problem(403, 'TOTP_REQUIRED')));
    const section = await openOutcome('moderator');
    pick(section, 'выигран');
    fireEvent.change(within(section).getByLabelText('Сумма договора'), { target: { value: '100' } });
    fireEvent.click(within(section).getByRole('button', { name: 'Сохранить' }));
    expect(await screen.findByRole('dialog')).toBeTruthy();
    expect(within(section).queryByRole('alert')).toBeNull();
  });
});
