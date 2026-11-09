/** FE-020 · соединение в приложении: полоса «Нет связи», восстановление, конец сессии. */
import { act, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';

import { FakeSocket } from '../test/fakeSocket';
import { renderApp } from '../test/render';

const wsOptions = { createSocket: FakeSocket.factory, backoff: () => 10 };

beforeEach(() => {
  FakeSocket.all = [];
});

async function signedIn() {
  renderApp('/', wsOptions);
  await screen.findByRole('navigation', { name: 'Разделы' });
  await waitFor(() => expect(FakeSocket.all.length).toBeGreaterThan(0));
  act(() => FakeSocket.last().open());
}

describe('SessionWs (FR-TREE-33, FR-SESS-02)', () => {
  it('разрыв — жёлтая полоса; переподключение — полоса пропадает', async () => {
    await signedIn();
    expect(screen.queryByText('Нет связи, правки не сохраняются')).toBeNull();
    act(() => FakeSocket.last().drop());
    expect(await screen.findByText('Нет связи, правки не сохраняются')).toBeTruthy();
    await waitFor(() => expect(FakeSocket.all).toHaveLength(2));
    act(() => FakeSocket.last().open());
    await waitFor(() => expect(screen.queryByText('Нет связи, правки не сохраняются')).toBeNull());
  });

  it('session.ended — экран входа с возвратом на текущий адрес', async () => {
    await signedIn();
    act(() =>
      FakeSocket.last().push({
        type: 'event',
        event: 'session.ended',
        channel: 'user:u1',
        ts: '2026-11-09T10:00:00Z',
        data: { reason: 'expired' },
      }),
    );
    await waitFor(() => expect(window.location.pathname).toBe('/login'));
    expect(window.location.search).toBe('?next=%2F');
  });
});
