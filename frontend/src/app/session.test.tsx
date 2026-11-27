/** FE-003 · смена пользователя в одной вкладке: после выхода и входа шапка — нового пользователя. */
import { QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { describe, expect, it } from 'vitest';

import { PERSONAS } from '../shared/api/mocks/personas';
import { persona } from '../test/setup';
import { createQueryClient } from './App';
import { SessionProvider, useSession } from './session';

describe('SessionProvider', () => {
  it('после clear() и входа другим пользователем refresh() читает /me заново', async () => {
    persona.current = PERSONAS.superadmin;
    const client = createQueryClient();
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>
        <SessionProvider>{children}</SessionProvider>
      </QueryClientProvider>
    );
    const { result } = renderHook(() => useSession(), { wrapper });
    await waitFor(() => expect(result.current.session).toMatchObject({ me: { login: 'superadmin' } }));

    act(() => result.current.clear()); // «Выйти»
    persona.current = PERSONAS.moderator; // вход другим пользователем
    await act(() => result.current.refresh());

    await waitFor(() => expect(result.current.session).toMatchObject({ me: { login: 'a.smirnova' } }));
  });
});
