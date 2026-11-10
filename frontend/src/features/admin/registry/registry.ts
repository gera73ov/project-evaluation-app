/**
 * FE-073 · правила реестра и режима поддержки (FR-ADM-06, BR-PRJ-07, FR-ADM-05): кого можно
 * назначить модератором, причина 10–500 символов, сколько осталось от 60 минут сессии.
 */
import type { components } from '../../../shared/api/client';

type User = components['schemas']['User'];

export const registryKey = ['admin', 'registry'] as const;

/** Модератор проекта — пользователь с системной ролью «Модератор» или «Руководитель пресейла». */
export const canModerate = (u: Pick<User, 'status' | 'system_roles'>) =>
  u.status === 'active' && u.system_roles.some((r) => r.role === 'moderator' || r.role === 'presale_head');

export const REASON_MIN = 10;
export const REASON_MAX = 500;
export const reasonValid = (s: string) => s.trim().length >= REASON_MIN && s.trim().length <= REASON_MAX;

/** Минуты до конца сессии, округление вверх; 0 — сессия закончилась. */
export const minutesLeft = (expiresAt: string, now: number) =>
  Math.max(0, Math.ceil((Date.parse(expiresAt) - now) / 60_000));

const KEY = (projectId: string) => `estimator.support.reason.${projectId}`;

/** Причина видна в жёлтой полосе; API проекта её не отдаёт — она хранится во вкладке. */
export function rememberSupportReason(projectId: string, reason: string) {
  try {
    sessionStorage.setItem(KEY(projectId), reason);
  } catch {
    // хранилище недоступно — полоса покажется без причины
  }
}

export function supportReason(projectId: string): string | null {
  try {
    return sessionStorage.getItem(KEY(projectId));
  } catch {
    return null;
  }
}
