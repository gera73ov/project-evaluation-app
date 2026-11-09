/** FE-043 · «Вопросы заказчику» (11.11) и «Обсуждения» (11.10): правила, права, выгрузка, действия. */
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { components } from '../../../shared/api/client';
import { PROJECTS } from '../../../shared/api/mocks/data';
import { PERSONAS } from '../../../shared/api/mocks/personas';
import { persona, server } from '../../../test/setup';
import { renderApp } from '../../../test/render';
import { countByStatus, cqActions, defaultSelection, questionNo, waitingDays } from './questions';

type CustomerQuestion = components['schemas']['CustomerQuestion'];
type Thread = components['schemas']['Thread'];

const thread = (fields: Partial<Thread>) =>
  ({ id: 't', opened_by: { id: 'me' }, customer_status: 'new', ...fields }) as unknown as Thread;
const q = (id: string, status: Thread['customer_status']) =>
  ({ thread: thread({ id, customer_status: status }), path: [], answer: null }) as unknown as CustomerQuestion;

describe('правила вкладки', () => {
  it('номер В-NNN', () => {
    expect(questionNo(6)).toBe('В-006');
    expect(questionNo(1234)).toBe('В-1234');
  });

  it('числа на чипах и выбор по умолчанию — все «новые»', () => {
    const items = [q('a', 'new'), q('b', 'sent'), q('c', 'new'), q('d', 'withdrawn')];
    const counts = countByStatus(items);
    expect([counts.get('all'), counts.get('new'), counts.get('sent'), counts.get('closed')]).toEqual([4, 2, 1, 0]);
    expect(defaultSelection(items)).toEqual(['a', 'c']);
  });

  it('«ждём N дней» — полные сутки после отправки', () => {
    expect(waitingDays('2026-10-31T09:00:00Z', new Date('2026-11-03T10:00:00Z'))).toBe(3);
    expect(waitingDays('2026-11-03T09:00:00Z', new Date('2026-11-03T10:00:00Z'))).toBe(0);
  });

  it('действия: ответ — отправленному; снять отправленный — только с cq.manage', () => {
    const expert = ['cq.read', 'cq.withdraw'];
    const moderator = ['cq.read', 'cq.manage', 'cq.withdraw', 'cq.answer'];
    expect(cqActions(thread({ customer_status: 'new' }), expert, 'me')).toEqual({ answer: false, withdraw: true });
    expect(cqActions(thread({ customer_status: 'new' }), expert, 'other')).toEqual({ answer: false, withdraw: false });
    expect(cqActions(thread({ customer_status: 'sent' }), expert, 'me')).toEqual({ answer: false, withdraw: false });
    expect(cqActions(thread({ customer_status: 'sent' }), moderator, 'x')).toEqual({ answer: true, withdraw: true });
    expect(cqActions(thread({ customer_status: 'answered' }), moderator, 'x')).toEqual({
      answer: false,
      withdraw: false,
    });
  });
});

const portal = PROJECTS.portal;

async function openTab(tab: 'questions' | 'discussions', who: 'expert' | 'moderator' | 'presale') {
  persona.current = who === 'expert' ? PERSONAS.expert : who === 'moderator' ? PERSONAS.moderator : PERSONAS.presale;
  renderApp(`/projects/${portal.id}/stats/${tab}`);
  return screen.findByRole('table');
}

const rowOf = (table: HTMLElement, text: RegExp) =>
  within(table)
    .getAllByRole('row')
    .find((r) => text.test(r.textContent ?? '')) as HTMLElement;

afterEach(() => {
  server.events.removeAllListeners();
});

describe('вкладка «Вопросы заказчику»', () => {
  it('пресейл: чипы с числами, новые отмечены, плашки как на макете', async () => {
    const table = await openTab('questions', 'presale');
    await within(table).findByText('В-006');
    expect(screen.getByRole('button', { name: /Все\s*6/ })).toBeTruthy();
    expect(screen.getByRole('button', { name: /Отправлены\s*2/ })).toBeTruthy();
    expect((screen.getByRole('checkbox', { name: 'Выбрать В-006 для выгрузки' }) as HTMLInputElement).checked).toBe(
      true,
    );
    expect((screen.getByRole('checkbox', { name: 'Выбрать В-005 для выгрузки' }) as HTMLInputElement).checked).toBe(
      false,
    );
    expect(screen.getByText('Выбрано: 1')).toBeTruthy();
    expect(within(rowOf(table, /В-005/)).getByText('изменён после отправки')).toBeTruthy();
    expect(within(rowOf(table, /В-004/)).getByText('Проект целиком')).toBeTruthy();
    expect(within(rowOf(table, /В-004/)).getByText(/^ждём \d+/)).toBeTruthy();
    expect(within(rowOf(table, /В-003/)).getByText(/внёс П\. Сидоров/)).toBeTruthy();
    expect(within(rowOf(table, /В-001/)).getByText('Снят: дублирует В-003')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: /Отвечены/ }));
    expect(within(screen.getByRole('table')).getAllByRole('row')).toHaveLength(2);
  });

  it('эксперт: нет флажков и кнопок выгрузки', async () => {
    const table = await openTab('questions', 'expert');
    await within(table).findByText('В-006');
    expect(screen.queryAllByRole('checkbox')).toHaveLength(0);
    expect(screen.queryByRole('button', { name: /Word/ })).toBeNull();
    expect(screen.queryByRole('button', { name: '⇩ Excel' })).toBeNull();
    expect(screen.queryByText(/Выбрано/)).toBeNull();
    // свой новый вопрос эксперт может снять, чужой отправленный — нет
    expect(within(rowOf(table, /В-006/)).getByRole('button', { name: 'Снять' })).toBeTruthy();
    expect(within(rowOf(table, /В-004/)).queryByRole('button', { name: 'Снять' })).toBeNull();
  });

  it('выгрузка в Word: выбранные вопросы, «новые» становятся «отправлен»', async () => {
    Object.assign(URL, { createObjectURL: vi.fn(() => 'blob:x'), revokeObjectURL: vi.fn() });
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined);
    const bodies: unknown[] = [];
    server.events.on('request:start', ({ request }) => {
      if (request.method === 'POST' && request.url.includes('/customer-questions/export'))
        void request
          .clone()
          .json()
          .then((b) => bodies.push(b));
    });
    await openTab('questions', 'moderator');
    await screen.findByText('Выбрано: 1');
    fireEvent.click(screen.getByRole('checkbox', { name: 'Выбрать В-005 для выгрузки' }));
    expect(screen.getByText('Выбрано: 2')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: /Выгрузить в Word/ }));
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect((bodies[0] as { format: string; thread_ids: string[] }).format).toBe('docx');
    expect((bodies[0] as { thread_ids: string[] }).thread_ids).toHaveLength(2);
    await waitFor(() => expect(screen.getByRole('button', { name: /Новые\s*0/ })).toBeTruthy(), { timeout: 5000 });
    click.mockRestore();
  });

  it('модератор вносит ответ заказчика', async () => {
    const table = await openTab('questions', 'moderator');
    await within(table).findByText('В-004');
    fireEvent.click(within(rowOf(table, /В-004/)).getByRole('button', { name: 'Внести ответ заказчика' }));
    const dialog = await screen.findByRole('dialog', { name: 'Ответ заказчика на В-004' });
    const save = within(dialog).getByRole('button', { name: 'Внести ответ' }) as HTMLButtonElement;
    expect(save.disabled).toBe(true);
    fireEvent.change(within(dialog).getByRole('textbox', { name: 'Текст ответа' }), {
      target: { value: 'Только десктоп' },
    });
    fireEvent.click(save);
    await waitFor(() =>
      expect(within(rowOf(screen.getByRole('table'), /В-004/)).getByText(/Только десктоп/)).toBeTruthy(),
    );
    expect(within(rowOf(screen.getByRole('table'), /В-004/)).getByText(/отвечен/)).toBeTruthy();
  });

  it('снять вопрос с причиной', async () => {
    const table = await openTab('questions', 'moderator');
    await within(table).findByText('В-006');
    fireEvent.click(within(rowOf(table, /В-006/)).getByRole('button', { name: 'Снять' }));
    const dialog = await screen.findByRole('dialog', { name: 'Снять вопрос В-006?' });
    fireEvent.change(within(dialog).getByRole('textbox', { name: 'Причина снятия' }), {
      target: { value: 'уже обсудили' },
    });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Снять' }));
    await waitFor(() => expect(screen.getByText('Снят: уже обсудили')).toBeTruthy());
  });

  it('клик по вопросу открывает узел', async () => {
    const table = await openTab('questions', 'expert');
    fireEvent.click(await within(table).findByRole('button', { name: /протокол обмена с 1С/ }));
    await waitFor(() => expect(window.location.pathname).toBe(`/projects/${portal.id}`));
    expect(new URLSearchParams(window.location.search).get('node')).toBeTruthy();
  });
});

describe('вкладка «Обсуждения»', () => {
  it('все вопросы проекта с путями; фильтр по статусу', async () => {
    const table = await openTab('discussions', 'expert');
    await within(table).findByText(/Требуется ли поддержка мобильных браузеров/);
    expect(within(rowOf(table, /мобильных браузеров/)).getByText('Проект целиком')).toBeTruthy();
    await waitFor(() =>
      expect(
        within(rowOf(screen.getByRole('table'), /Обмен с 1С/)).getByText('Разработка › Бэкенд › Обмен с 1С'),
      ).toBeTruthy(),
    );
    expect(screen.queryAllByRole('checkbox')).toHaveLength(0);
    fireEvent.click(screen.getByRole('button', { name: /Решены/ }));
    expect(within(screen.getByRole('table')).getAllByRole('row')).toHaveLength(2);
  });
});
