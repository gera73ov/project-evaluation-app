/** FE-013 · команда (11.6 №4–6, №12): убрать, ревьюер, последний модератор, «нет эксперта», только чтение. */
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { PROJECTS } from '../../../shared/api/mocks/data';
import { PERSONAS } from '../../../shared/api/mocks/personas';
import { persona, server } from '../../../test/setup';
import { HttpResponse, api, http, renderApp } from '../../../test/render';

const id = PROJECTS.portal.id;

async function openTeam() {
  renderApp(`/projects/${id}/settings`);
  const section = await screen.findByRole('region', { name: 'Команда' });
  await within(section).findByText('О. Кузнецова');
  return section;
}

function capturePut() {
  const bodies: { members: { user_id: string; role: string; is_reviewer?: boolean }[] }[] = [];
  server.use(
    http.put(api('/projects/:id/members'), async ({ request }) => {
      const body = (await request.json()) as (typeof bodies)[number];
      bodies.push(body);
      return HttpResponse.json({ items: [] });
    }),
  );
  return bodies;
}

describe('настройки: «Команда»', () => {
  it('модератор убирает эксперта: PUT с полным составом без него', async () => {
    persona.current = PERSONAS.moderator;
    const bodies = capturePut();
    const section = await openTeam();
    const before = section.querySelectorAll('.person').length;
    fireEvent.click(within(section).getByRole('button', { name: 'Убрать О. Кузнецова' }));
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]?.members).toHaveLength(before - 1);
  });

  it('«Сделать ревьюером» меняет только is_reviewer этого эксперта', async () => {
    persona.current = PERSONAS.moderator;
    const bodies = capturePut();
    const section = await openTeam();
    fireEvent.click(within(section).getByRole('button', { name: 'О. Кузнецова' }));
    fireEvent.click(await screen.findByRole('menuitem', { name: 'Сделать ревьюером' }));
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]?.members.filter((m) => m.is_reviewer).length).toBeGreaterThan(0);
  });

  it('последнего модератора убрать нельзя; заблокированный — плашка', async () => {
    persona.current = PERSONAS.moderator;
    const section = await openTeam();
    expect(within(section).getByRole('button', { name: 'Убрать А. Смирнова' }).hasAttribute('disabled')).toBe(true);
    expect(within(section).getByText(/заблокирован/)).toBeTruthy();
  });

  it('дисциплина без эксперта — «нет эксперта»', async () => {
    persona.current = PERSONAS.moderator;
    server.use(http.get(api('/projects/:id/members'), () => HttpResponse.json({ items: [] })));
    renderApp(`/projects/${id}/settings`);
    const section = await screen.findByRole('region', { name: 'Команда' });
    await waitFor(() => expect(within(section).getAllByText('нет эксперта').length).toBeGreaterThan(0));
  });

  it('эксперт: без кнопок правки и добавления дисциплины', async () => {
    const section = await openTeam();
    expect(within(section).queryByRole('button', { name: /Убрать/ })).toBeNull();
    expect(within(section).queryByRole('button', { name: '+ Добавить дисциплину' })).toBeNull();
  });
  it('«+» у дисциплины: поиск кандидатов (CR-005) и PUT с новым экспертом', async () => {
    persona.current = PERSONAS.moderator;
    const bodies = capturePut();
    const asked = { params: new URLSearchParams() };
    server.use(
      http.get(api('/projects/:id/member-candidates'), ({ request }) => {
        asked.params = new URL(request.url).searchParams;
        return HttpResponse.json({
          items: [{ user: { id: 'u-new', full_name: 'Е. Новая', initials: 'ЕН' }, system_roles: [] }],
        });
      }),
    );
    const section = await openTeam();
    fireEvent.click(within(section).getByRole('button', { name: 'Добавить эксперта: QA' }));
    const dialog = await screen.findByRole('dialog', { name: 'Добавить эксперта' });
    fireEvent.change(within(dialog).getByRole('textbox', { name: 'ФИО' }), { target: { value: 'Но' } });
    fireEvent.click(await within(dialog).findByRole('button', { name: /Е\. Новая/ }));
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(asked.params.get('role')).toBe('expert');
    expect(asked.params.get('q')).toBe('Но');
    expect(bodies[0]?.members).toContainEqual(
      expect.objectContaining({ user_id: 'u-new', role: 'expert', is_reviewer: false }),
    );
  });

  it('«Заменить…» у заблокированного: POST replace с выбранным человеком', async () => {
    persona.current = PERSONAS.moderator;
    let body: unknown = null;
    let path = '';
    server.use(
      http.get(api('/projects/:id/member-candidates'), () =>
        HttpResponse.json({
          items: [{ user: { id: 'u-new', full_name: 'Е. Новая', initials: 'ЕН' }, system_roles: [] }],
        }),
      ),
      http.post(api('/projects/:id/members/:userId/replace'), async ({ request, params }) => {
        body = await request.json();
        path = String(params.userId);
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const section = await openTeam();
    fireEvent.click(within(section).getByRole('button', { name: 'Заменить…' }));
    const dialog = await screen.findByRole('dialog', { name: /Заменить Н\. Новиков/ });
    fireEvent.change(within(dialog).getByRole('textbox', { name: 'ФИО' }), { target: { value: 'Но' } });
    fireEvent.click(await within(dialog).findByRole('button', { name: /Е\. Новая/ }));
    await waitFor(() => expect(body).toEqual({ replacement_user_id: 'u-new' }));
    expect(path).not.toBe('');
  });
});
