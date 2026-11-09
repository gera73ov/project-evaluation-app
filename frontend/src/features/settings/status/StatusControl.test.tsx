/** FE-015 · статус проекта (FR-PRJ-05): 8 переходов и их подтверждения, причина отмены, копирование. */
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import i18n from 'i18next';
import { describe, expect, it } from 'vitest';

import { PROJECTS } from '../../../shared/api/mocks/data';
import { PERSONAS } from '../../../shared/api/mocks/personas';
import { persona, server } from '../../../test/setup';
import { HttpResponse, api, http, renderApp } from '../../../test/render';
import { TRANSITIONS, confirmationFor, type StatusFacts } from './StatusControl';

const id = PROJECTS.portal.id;
const t = i18n.t.bind(i18n);

const clean: StatusFacts = {
  experts: 5,
  disciplinesWithoutExpert: [],
  branchesNotDone: [],
  openQuestions: 0,
  hasSnapshot: true,
};
const dirty: StatusFacts = {
  experts: 3,
  disciplinesWithoutExpert: ['DevOps'],
  branchesNotDone: ['Разработка · Бэкенд'],
  openQuestions: 2,
  hasSnapshot: false,
};

describe('переходы статуса (диаграмма 4.2, FR-PRJ-05)', () => {
  it('восемь переходов, у каждого статуса — только свои', () => {
    const all = [...TRANSITIONS.values()].flat();
    expect(all.map((tr) => tr.key).sort()).toEqual(
      ['archive', 'cancel', 'complete', 'consolidate', 'reopen', 'restore', 'return', 'start'].sort(),
    );
    expect(TRANSITIONS.get('estimation')?.map((tr) => tr.to)).toEqual(['consolidation', 'archived']);
  });

  it('«Запустить оценку»: число экспертов и дисциплины без эксперта', () => {
    const c = confirmationFor('start', dirty, t);
    expect(c).toEqual({
      kind: 'confirm',
      question: 'Эксперты (3) получат письмо и увидят проект. Запустить?',
      warnings: ['Дисциплины без эксперта: DevOps'],
    });
    expect(confirmationFor('start', clean, t)).toMatchObject({ kind: 'confirm', warnings: [] });
  });

  it('«Перейти к сведению» без вопроса, если все ветки готовы; иначе список веток', () => {
    expect(confirmationFor('consolidate', clean, t)).toEqual({ kind: 'none' });
    expect(confirmationFor('consolidate', dirty, t)).toEqual({
      kind: 'confirm',
      question: null,
      warnings: ['Ветки не готовы: Разработка · Бэкенд'],
    });
    expect(confirmationFor('return', dirty, t)).toEqual({ kind: 'none' });
  });

  it('«Завершить»: предупреждения о ветках, вопросах заказчику и снимке', () => {
    expect(confirmationFor('complete', dirty, t)).toMatchObject({
      kind: 'confirm',
      warnings: ['Ветки не готовы: Разработка · Бэкенд', 'Открытые вопросы заказчику: 2', 'Нет ни одного снимка'],
    });
    expect(confirmationFor('complete', clean, t)).toMatchObject({ kind: 'confirm', warnings: [] });
  });

  it('переоткрыть, в архив, восстановить — подтверждение; отмена — причина', () => {
    expect(confirmationFor('reopen', clean, t)).toMatchObject({
      question: 'Эксперты снова смогут править. Переоткрыть?',
    });
    expect(confirmationFor('archive', clean, t)).toMatchObject({ kind: 'confirm' });
    expect(confirmationFor('restore', clean, t)).toMatchObject({ kind: 'confirm' });
    expect(confirmationFor('cancel', clean, t)).toEqual({ kind: 'reason' });
  });
});

function captureStatus() {
  const bodies: { to: string; reason?: string }[] = [];
  server.use(
    http.post(api('/projects/:id/status'), async ({ request }) => {
      const body = (await request.json()) as (typeof bodies)[number];
      bodies.push(body);
      return HttpResponse.json({ status: body.to, project_version: 22, warnings: [] });
    }),
  );
  return bodies;
}

async function openMenu() {
  renderApp(`/projects/${id}/settings`);
  const button = await screen.findByRole('button', { name: /Статус проекта: Оценка/ });
  fireEvent.click(button);
  const item = await screen.findByRole('menuitem', { name: 'Перейти к сведению' });
  await waitFor(() => expect(item.hasAttribute('data-disabled')).toBe(false), { timeout: 3000 });
}

describe('кнопка статуса в настройках', () => {
  it('«Перейти к сведению» с ветками «черновик» — список веток, затем POST', async () => {
    persona.current = PERSONAS.moderator;
    const bodies = captureStatus();
    await openMenu();
    fireEvent.click(screen.getByRole('menuitem', { name: 'Перейти к сведению' }));
    const dialog = await screen.findByRole('dialog', { name: 'Перейти к сведению' });
    expect(within(dialog).getByText(/^Ветки не готовы:/)).toBeTruthy();
    fireEvent.click(within(dialog).getByRole('button', { name: 'Перейти к сведению' }));
    await waitFor(() => expect(bodies).toEqual([{ to: 'consolidation' }]));
  });

  it('«Отменить проект…»: причина от 10 символов обязательна', async () => {
    persona.current = PERSONAS.moderator;
    const bodies = captureStatus();
    await openMenu();
    fireEvent.click(screen.getByRole('menuitem', { name: 'Отменить проект…' }));
    const dialog = await screen.findByRole('dialog', { name: 'Отменить проект' });
    const reason = within(dialog).getByRole('textbox', { name: /Причина отмены/ });
    fireEvent.change(reason, { target: { value: 'коротко' } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Отменить проект' }));
    await within(dialog).findByText('От 10 до 500 символов');
    expect(bodies).toHaveLength(0);
    fireEvent.change(reason, { target: { value: '  Заказчик отказался от тендера  ' } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Отменить проект' }));
    await waitFor(() => expect(bodies).toEqual([{ to: 'archived', reason: 'Заказчик отказался от тендера' }]));
  });

  it('эксперт видит плашку статуса, без кнопки и «⋯»', async () => {
    persona.current = PERSONAS.expert;
    renderApp(`/projects/${id}/settings`);
    await screen.findByRole('region', { name: 'Команда' });
    expect(screen.queryByRole('button', { name: /Статус проекта/ })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Ещё действия с проектом' })).toBeNull();
    expect(document.querySelector('.crumbs .pill')?.textContent).toBe('Оценка');
  });

  it('«Копировать проект…» создаёт копию и открывает её настройки', async () => {
    persona.current = PERSONAS.moderator;
    let body: unknown = null;
    server.use(
      http.post(api('/projects/:id/copy'), async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({ project: { id: PROJECTS.fns.id }, project_version: 1 }, { status: 201 });
      }),
    );
    renderApp(`/projects/${id}/settings`);
    fireEvent.click(await screen.findByRole('button', { name: 'Ещё действия с проектом' }));
    fireEvent.click(await screen.findByRole('menuitem', { name: 'Копировать проект…' }));
    const dialog = await screen.findByRole('dialog', { name: 'Копировать проект' });
    expect((within(dialog).getByRole('textbox', { name: 'Название копии' }) as HTMLInputElement).value).toBe(
      'Портал дилеров (копия)',
    );
    fireEvent.click(within(dialog).getByRole('button', { name: 'Копировать' }));
    await waitFor(() => expect(body).toEqual({ name: 'Портал дилеров (копия)' }));
    await waitFor(() => expect(window.location.pathname).toBe(`/projects/${PROJECTS.fns.id}/settings`));
  });
});
