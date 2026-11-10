/**
 * FE-060 · маршруты раздела «Система» для вошедшего суперадминистратора. FE-064: пока мастер
 * первичной настройки не пройден, раздел открывает мастер с прерванного шага (SPEC 7.1).
 */
import type { ReactNode } from 'react';

import { Redirect } from '../../app/router';
import { useSession, type Me } from '../../app/session';
import { currentStep, useSetup } from '../setup-wizard/setup';

export function SystemRoute({ render }: { render: (me: Me) => ReactNode }) {
  const { session } = useSession();
  const setup = useSetup();
  if (session.state !== 'ready') return null;
  if (setup.isPending) return null;
  if (setup.data && currentStep(setup.data) !== null) return <Redirect to="/setup" />;
  return <>{render(session.me)}</>;
}
