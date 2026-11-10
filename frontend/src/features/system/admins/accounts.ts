/**
 * FE-063 · правила учёток раздела «Система» (BR-ROLE-02/03): какие учётки в каком пункте меню,
 * последний активный суперадминистратор, предел в три суперадминистратора.
 */
import type { components } from '../../../shared/api/client';

type Account = components['schemas']['AdminAccount'];
export type AdminRole = Account['roles'][number];
export type AccountKind = 'admins' | 'auditors';

export const SUPERADMIN_MAX = 3;

/** «Суперадминистраторы и администраторы» — все, кроме аудиторов; «Аудиторы ИБ» — только они. */
export function accountsOf(items: readonly Account[], kind: AccountKind): Account[] {
  const auditor = (a: Account) => a.roles.includes('security_auditor');
  const order = (a: Account) => (a.roles.includes('superadmin') ? 0 : 1);
  return items
    .filter((a) => (kind === 'auditors' ? auditor(a) : !auditor(a)))
    .sort((a, b) => order(a) - order(b) || a.full_name.localeCompare(b.full_name, 'ru'));
}

/** Последнего активного суперадминистратора нельзя заблокировать, разжаловать и анонимизировать. */
export function isLastSuperadmin(account: Account, items: readonly Account[]): boolean {
  if (!account.roles.includes('superadmin') || account.status !== 'active') return false;
  return items.filter((a) => a.status === 'active' && a.roles.includes('superadmin')).length === 1;
}
