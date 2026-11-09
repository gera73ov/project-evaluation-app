/** FE-060 · маршруты раздела «Система» для вошедшего суперадминистратора. */
import type { ReactNode } from 'react';

import { useSession, type Me } from '../../app/session';

export function SystemRoute({ render }: { render: (me: Me) => ReactNode }) {
  const { session } = useSession();
  return session.state === 'ready' ? <>{render(session.me)}</> : null;
}
