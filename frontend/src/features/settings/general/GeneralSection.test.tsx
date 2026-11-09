/** FE-012 · «Основное» и УП (11.6 №2, №3, №10, №11): сохранение по уходу фокуса, подтверждение, чтение. */
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { api as client } from '../../../shared/api/client';
import { PERSONAS } from '../../../shared/api/mocks/personas';
import { PROJECTS } from '../../../shared/api/mocks/data';
import { problem } from '../../../test/render';
import { persona, server } from '../../../test/setup';
import { HttpResponse, api, http, renderApp } from '../../../test/render';
import { parsePercent, parseWeeks } from './GeneralSection';

const id = PROJECTS.portal.id;

async function projectBody(): Promise<Record<string, unknown>> {
  const { data } = await client.GET('/projects/{id}', { params: { path: { id } } });
  return data as unknown as Record<string, unknown>;
}

async function openSettings() {
  renderApp(`/projects/${id}/settings`);
  return screen.findByRole('region', { name: 'Основное' });
}

describe('разбор полей', () => {
  it('процент УП 0–50 с шагом 0,5', () => {
    expect(parsePercent('18')).toBe('18');
    expect(parsePercent('18,5 %')).toBe('18.5');
    expect(parsePercent('0')).toBe('0');
    expect(parsePercent('50')).toBe('50');
    expect(parsePercent('50,5')).toBeNull();
    expect(parsePercent('18,3')).toBeNull();
    expect(parsePercent('abc')).toBeNull();
  });
  it('срок 1–260 недель или пусто', () => {
    expect(parseWeeks('')).toBeNull();
    expect(parseWeeks('14')).toBe(14);
    expect(parseWeeks('0')).toBeUndefined();
    expect(parseWeeks('261')).toBeUndefined();
    expect(parseWeeks('1,5')).toBeUndefined();
  });
});

describe('настройки: «Основное»', () => {
  it('модератор: поле сохраняется при уходе фокуса одним полем и показывает «✓ сохранено»', async () => {
    persona.current = PERSONAS.moderator;
    const base = await projectBody();
    let body: unknown = null;
    server.use(
      http.patch(api('/projects/:id'), async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({ project: { ...base, pm_percent: '20' }, project_version: 23 });
      }),
    );
    const section = await openSettings();
    const pm = within(section).getByLabelText('Управление проектом');
    fireEvent.change(pm, { target: { value: '20' } });
    fireEvent.blur(pm);
    await waitFor(() => expect(body).toEqual({ pm_percent: '20', confirm: false }));
    expect(await within(section).findByText('✓ сохранено')).toBeTruthy();
  });

  it('неверный процент — ошибка у поля, запроса нет', async () => {
    persona.current = PERSONAS.moderator;
    let called = false;
    server.use(
      http.patch(api('/projects/:id'), () => {
        called = true;
        return HttpResponse.json({});
      }),
    );
    const section = await openSettings();
    const pm = within(section).getByLabelText('Управление проектом');
    fireEvent.change(pm, { target: { value: '55' } });
    fireEvent.blur(pm);
    expect(await within(section).findByText('От 0 до 50 с шагом 0,5')).toBeTruthy();
    expect(called).toBe(false);
  });

  it('выключение фазы с оценками: 409 → диалог → повтор с confirm: true', async () => {
    persona.current = PERSONAS.moderator;
    const base = await projectBody();
    const bodies: Record<string, unknown>[] = [];
    server.use(
      http.patch(api('/projects/:id'), async ({ request }) => {
        const body = (await request.json()) as Record<string, unknown>;
        bodies.push(body);
        if (!body.confirm) return problem(409, 'CONFIRMATION_REQUIRED', { consequence: 'branches_to_trash', affected: 5 });
        return HttpResponse.json({ project: base, project_version: 24 });
      }),
    );
    const section = await openSettings();
    const phases = within(section).getByRole('group', { name: 'Фазы' });
    fireEvent.click(within(phases).getByRole('button', { name: /Тестирование/ }));
    expect(await screen.findByText(/ветки \(5\) уйдут в корзину/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Выключить фазу' }));
    await waitFor(() => expect(bodies).toHaveLength(2));
    expect(bodies[1]).toMatchObject({ confirm: true, phases: [{ is_enabled: false }] });
    // сквозная фаза не выключается
    expect(within(phases).getByRole('button', { name: /Управление проектом · всегда/ }).hasAttribute('disabled')).toBe(true);
  });

  it('эксперт: только просмотр, кнопки фаз неактивны', async () => {
    const section = await openSettings();
    expect(screen.getByText('Только просмотр: настройки меняет модератор проекта')).toBeTruthy();
    expect((within(section).getByLabelText('Название') as HTMLInputElement).readOnly).toBe(true);
    const phases = within(section).getByRole('group', { name: 'Фазы' });
    for (const button of within(phases).getAllByRole('button')) expect(button.hasAttribute('disabled')).toBe(true);
  });
});
