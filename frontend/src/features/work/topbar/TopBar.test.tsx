/** FE-023 · верхняя полоса: итоги из расчёта, деньги только у ролей с деньгами, «Открыто», дедлайн. */
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';

import { PROJECTS } from '../../../shared/api/mocks/data';
import { PERSONAS } from '../../../shared/api/mocks/personas';
import { persona, server } from '../../../test/setup';
import { HttpResponse, api, http, problem, renderApp } from '../../../test/render';
import { openQuestions, riskCount } from '../WorkPage';
import { toTreeNode } from '../store/treeStore';
import { workingDaysLeft } from './TopBar';

const id = PROJECTS.portal.id;

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

describe('расчёты полосы', () => {
  it('рабочие дни до дедлайна без выходных', () => {
    const friday = new Date(2026, 10, 6);
    expect(workingDaysLeft('2026-11-06', friday)).toBe(0);
    expect(workingDaysLeft('2026-11-09', friday)).toBe(1);
    expect(workingDaysLeft('2026-11-10', friday)).toBe(2);
    expect(workingDaysLeft('2026-11-05', friday)).toBe(-1);
  });

  it('«Открыто» и «Риски» считаются по узлам', () => {
    const node = (nid: string, extra: Record<string, unknown>) =>
      toTreeNode({ id: nid, kind: 'item', phase_id: 'p', parent_id: null, title: nid, ...extra });
    const nodes = new Map([
      ['a', node('a', { open_questions: 2, questions_to_me: 0, comment_lines: [{ tag_id: 'risk', text: 'x' }] })],
      ['b', node('b', { open_questions: 1, questions_to_me: 1, comment_lines: [{ tag_id: 'tech', text: 'y' }] })],
      ['c', node('c', { open_questions: 0 })],
    ]);
    expect(openQuestions({ nodes }).map((q) => [q.nodeId, q.open, q.toMe])).toEqual([
      ['b', 1, 1],
      ['a', 2, 0],
    ]);
    expect(riskCount({ nodes }, new Set(['risk']))).toBe(1);
  });
});

describe('верхняя полоса рабочего экрана', () => {
  it('у эксперта денег нет в разметке и они не запрашиваются', async () => {
    persona.current = PERSONAS.expert;
    let moneyAsked = false;
    server.use(
      http.get(api('/projects/:id/money'), () => {
        moneyAsked = true;
        return HttpResponse.json({});
      }),
    );
    renderApp(`/projects/${id}`);
    const bar = await screen.findByRole('banner', { name: 'Проект' });
    await within(bar).findByText('406,5');
    expect(within(bar).getByText('425,5')).toBeTruthy();
    expect(within(bar).getByText('в КП')).toBeTruthy();
    expect(bar.textContent).not.toMatch(/без оценки/);
    expect(within(bar).queryByLabelText('Сумма для КП')).toBeNull();
    expect(bar.textContent).not.toMatch(/USD|₽|НДС/);
    expect(moneyAsked).toBe(false);
    expect(within(bar).queryByRole('button', { name: /Статус проекта/ })).toBeNull();
  });

  it('у модератора — сумма в валюте КП без НДС и с НДС, кнопка статуса', async () => {
    persona.current = PERSONAS.moderator;
    renderApp(`/projects/${id}`);
    const bar = await screen.findByRole('banner', { name: 'Проект' });
    const money = await within(bar).findByLabelText('Сумма для КП');
    expect(money.textContent).toMatch(/12\s978\sUSD/);
    expect(money.textContent).toMatch(/15\s574\sUSD/);
    expect(within(bar).getByRole('button', { name: /Статус проекта: Оценка/ })).toBeTruthy();
  });

  it('без TOTP в сессии — замок вместо сумм', async () => {
    persona.current = PERSONAS.moderator;
    server.use(http.get(api('/projects/:id/money'), () => problem(403, 'TOTP_REQUIRED')));
    renderApp(`/projects/${id}`);
    const bar = await screen.findByRole('banner', { name: 'Проект' });
    await within(bar).findByText(/подтвердите вход кодом/);
    expect(bar.textContent).not.toMatch(/USD/);
  });

  it('«Открыто» — список вопросов, клик показывает строку', async () => {
    persona.current = PERSONAS.expert;
    renderApp(`/projects/${id}`);
    const bar = await screen.findByRole('banner', { name: 'Проект' });
    fireEvent.click(await within(bar).findByRole('button', { name: /Открыто/ }));
    const item = await screen.findByRole('button', { name: /Обмен с 1С/ });
    fireEvent.click(item);
    await waitFor(() => expect(document.querySelector('.tr.target')?.textContent).toContain('Обмен с 1С'));
  });
});
