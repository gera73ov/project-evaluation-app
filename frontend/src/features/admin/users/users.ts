/**
 * FE-070 · правила экрана «Пользователи» (SPEC 7.5, FR-AUTH-AD-10, FR-ADM-05, BR-ROLE-*):
 * какие роли администратор выдаёт сам, какие пришли из групп AD, кого можно выбрать заменой.
 */
import type { components } from '../../../shared/api/client';

export type User = components['schemas']['User'];
export type GrantableRole = 'moderator' | 'presale' | 'presale_head';

/** Роли, которые администратор выдаёт вручную (permissions.yaml: users.roles.grant). */
export const GRANTABLE: readonly GrantableRole[] = ['moderator', 'presale', 'presale_head'];

/** Роли, которые в режиме AD при включённом сопоставлении выдаются только группами. */
const FROM_GROUPS = new Set<string>(['moderator', 'presale']);

export const manualRoles = (u: User): GrantableRole[] =>
  GRANTABLE.filter((r) => u.system_roles.some((s) => s.role === r));

/**
 * Сопоставление групп включено: у учётки AD есть роль с источником «группа AD». Тогда «Модератор»
 * и «Пресейл» вручную не выдаются и не снимаются (FR-AUTH-AD-07).
 */
export const mappedByGroups = (u: User) => u.source === 'ad' && u.system_roles.some((s) => s.source === 'ad_group');

export const roleLocked = (u: User, role: GrantableRole, isSelf: boolean) =>
  isSelf || (mappedByGroups(u) && FROM_GROUPS.has(role));

/** Замена — активный пользователь, не сам заменяемый. */
export const replacementCandidates = (users: readonly User[], who: User) =>
  users.filter((u) => u.id !== who.id && u.status === 'active');

export const LOGIN_RE = /^[A-Za-z0-9._-]{3,64}$/;

export const AD_MIN_QUERY = 3;

export const usersKey = ['admin', 'users'] as const;
