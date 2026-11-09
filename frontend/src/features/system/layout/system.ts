/**
 * FE-060 · правила раздела «Система»: баннер единственного суперадминистратора (BR-ROLE-03) и
 * роли, у которых отключён обязательный второй фактор, хотя по умолчанию он нужен (FR-SA-04).
 */
import type { components } from '../../../shared/api/client';

type AdminAccount = components['schemas']['AdminAccount'];

/** Активный суперадминистратор ровно один — нужен красный баннер. */
export function soleSuperadmin(items: readonly AdminAccount[]): boolean {
  return items.filter((a) => a.status === 'active' && a.roles.includes('superadmin')).length === 1;
}

/**
 * Роли, для которых TOTP по умолчанию обязателен (settings.schema.json `security.mfa_policy`):
 * администратор и все роли с деньгами, плюс аудитор ИБ. «Пользователь» по умолчанию необязателен.
 */
export const MFA_DEFAULT_REQUIRED = ['admin', 'moderator', 'presale', 'presale_head', 'security_auditor'] as const;
export type MfaRole = (typeof MFA_DEFAULT_REQUIRED)[number];

/**
 * Роли, у которых суперадминистратор отключил обязательный TOTP. Значения раздела настроек
 * приходят по полным ключам (`security.mfa_policy`), как в settings.schema.json.
 */
export function mfaWarningRoles(values: object): MfaRole[] {
  const policy = new Map(Object.entries(values)).get('security.mfa_policy') as Record<string, unknown> | undefined;
  if (!policy || typeof policy !== 'object') return [];
  const entries = new Map(Object.entries(policy));
  return MFA_DEFAULT_REQUIRED.filter((role) => entries.get(role) === 'optional');
}
