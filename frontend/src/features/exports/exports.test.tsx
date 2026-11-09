/** FE-045 · «Экспорт ▾» и «📷 Снимок» на рабочем экране, «⇩» и «ошибочный» в списке снимков. */
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { PROJECTS } from '../../shared/api/mocks/data';
import { uuidFrom } from '../../shared/api/mocks/ids';
import { PERSONAS } from '../../shared/api/mocks/personas';
import { persona, server } from '../../test/setup';
import { renderApp } from '../../test/render';

const portal = PROJECTS.portal;

async function openWork(who: 'expert' | 'moderator') {
  persona.current = who === 'expert' ? PERSONAS.expert : PERSONAS.moderator;
  renderApp(`/projects/${portal.id}`);
  await screen.findByRole('treegrid', { name: 'Дерево оценки' });
}

function captureBodies(path: string) {
  const bodies: unknown[] = [];
  server.events.on('request:start', ({ request }) => {
    if (request.method === 'POST' && new URL(request.url).pathname === path)
      void request
        .clone()
        .json()
        .then((b) => bodies.push(b));
  });
  return bodies;
}

let click: ReturnType<typeof vi.spyOn>;
beforeEach(() => {
  Object.assign(URL, { createObjectURL: vi.fn(() => 'blob:x'), revokeObjectURL: vi.fn() });
  click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined);
});
afterEach(() => {
  click.mockRestore();
  server.events.removeAllListeners();
});

describe('«Экспорт ▾»', () => {
  it('эксперт: только «Часы», пункта с деньгами нет в DOM', async () => {
    await openWork('expert');
    fireEvent.click(screen.getByRole('button', { name: /Экспорт/ }));
    const menu = await screen.findByRole('dialog', { name: /Экспорт/ });
    expect(within(menu).getByRole('button', { name: /Excel «Часы»/ })).toBeTruthy();
    expect(within(menu).queryByRole('button', { name: /С деньгами/ })).toBeNull();
  });

  it('долгая выгрузка: «Готовим файл…», затем файл и «Файл готов»', async () => {
    const bodies = captureBodies(`/api/v1/projects/${portal.id}/exports`);
    await openWork('moderator');
    fireEvent.click(screen.getByRole('button', { name: /Экспорт/ }));
    const menu = await screen.findByRole('dialog', { name: /Экспорт/ });
    fireEvent.click(within(menu).getByRole('button', { name: /С деньгами/ }));
    await waitFor(() => expect(bodies).toEqual([{ kind: 'money_xlsx', snapshot_id: null }]));
    expect(await screen.findByText('Готовим файл…', {}, { timeout: 4000 })).toBeTruthy();
    expect(await screen.findByText('Файл готов', {}, { timeout: 4000 })).toBeTruthy();
    expect(click).toHaveBeenCalled();
  }, 12_000);
});

describe('«📷 Снимок»', () => {
  it('эксперт кнопки не видит', async () => {
    await openWork('expert');
    expect(screen.queryByRole('button', { name: /Снимок/ })).toBeNull();
  });

  it('модератор: название обязательно, снимок сохраняется', async () => {
    const bodies = captureBodies(`/api/v1/projects/${portal.id}/snapshots`);
    await openWork('moderator');
    fireEvent.click(screen.getByRole('button', { name: /Снимок/ }));
    const dialog = await screen.findByRole('dialog', { name: 'Снимок проекта' });
    const save = within(dialog).getByRole('button', { name: 'Сделать снимок' }) as HTMLButtonElement;
    expect(save.disabled).toBe(true);
    const name = within(dialog).getByRole('textbox', { name: /Название/ }) as HTMLInputElement;
    expect(name.maxLength).toBe(100);
    fireEvent.change(name, { target: { value: ' v3 — после созвона ' } });
    fireEvent.change(within(dialog).getByRole('textbox', { name: 'Описание' }), { target: { value: 'Учли SSO' } });
    fireEvent.click(save);
    await waitFor(() => expect(bodies).toEqual([{ name: 'v3 — после созвона', description: 'Учли SSO' }]));
    expect(await screen.findByText('Снимок «v3 — после созвона» сохранён')).toBeTruthy();
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Снимок проекта' })).toBeNull());
  });
});

describe('список снимков', () => {
  it('модератор помечает снимок «ошибочный»', async () => {
    persona.current = PERSONAS.moderator;
    renderApp(`/projects/${portal.id}/stats/snapshots`);
    const table = await screen.findByRole('table');
    const row = within(table)
      .getAllByRole('row')
      .find((r) => r.textContent?.includes('v2')) as HTMLElement;
    fireEvent.click(within(row).getByRole('button', { name: 'Пометить «ошибочный»' }));
    const dialog = await screen.findByRole('dialog', { name: 'Пометить снимок ошибочным?' });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Пометить «ошибочный»' }));
    await waitFor(() => expect((screen.getByRole('checkbox', { name: /v2/ }) as HTMLInputElement).disabled).toBe(true));
    expect(screen.getAllByText('ошибочный')).toHaveLength(2);
  });

  it('эксперт: «⇩» выгружает «Часы» из снимка, пометки нет', async () => {
    const bodies = captureBodies(`/api/v1/projects/${portal.id}/exports`);
    persona.current = PERSONAS.expert;
    renderApp(`/projects/${portal.id}/stats/snapshots`);
    fireEvent.click(await screen.findByRole('button', { name: /Выгрузить «v1 — КП отправлено»/ }));
    await waitFor(() =>
      expect(bodies).toEqual([{ kind: 'hours_xlsx', snapshot_id: uuidFrom('snapshot', 'portal', 'v1') }]),
    );
    expect(screen.queryByRole('button', { name: 'Пометить «ошибочный»' })).toBeNull();
  });
});
