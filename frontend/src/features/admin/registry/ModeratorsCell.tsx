/**
 * FE-094 · модераторы проекта в реестрах администратора и суперадминистратора. Сервер оставляет
 * заблокированного модератора в списке (`is_active: false`), а проект уже считается «без
 * модератора» (`no_moderator_since`, BR-PRJ-07): показываем и то, и другое.
 */
import { useTranslation } from 'react-i18next';

import type { components } from '../../../shared/api/client';

type UserRef = components['schemas']['UserRef'];

/** Модератор может вести проект, пока учётка активна; `is_active` нет — считаем активным. */
export const isActiveModerator = (m: UserRef) => m.is_active !== false;

export function ModeratorsCell({
  moderators,
  since,
  days,
}: {
  moderators: readonly UserRef[];
  since: string | null;
  days: number | null;
}) {
  const { t } = useTranslation();
  return (
    <>
      {moderators.map((m) => (
        <div key={m.id} className={isActiveModerator(m) ? undefined : 'sub'}>
          {m.full_name}
          {isActiveModerator(m) ? null : ` · ${t('admin.registry.blocked')}`}
        </div>
      ))}
      {since !== null || !moderators.some(isActiveModerator) ? (
        <span className="pill bad">{t('system.registry.noModerator', { count: days ?? 0 })}</span>
      ) : null}
    </>
  );
}
