/**
 * FE-071 · правила справочников администратора (SPEC 7.5, errors.yaml DICTIONARY_IN_USE): какие
 * записи нельзя удалить или отключить и почему — запреты показываются в интерфейсе, а не только
 * ответом сервера.
 */
import type { components } from '../../../shared/api/client';
import { asDecimalString } from '../../../shared/api/decimal';

type S = components['schemas'];
export type Phase = S['Phase'];
export type Discipline = S['Discipline'];
export type NodeType = S['NodeType'];
export type NodeTypeIcon = S['NodeTypeIcon'];
export type Norm = S['Norm'];
export type Profile = S['Profile'];
export type Ratio = S['Ratio'];
export type Tag = S['Tag'];
export type Currency = S['Currency'];
export type VatRate = S['VatRate'];
export type LossReason = S['LossReason'];
export type MethodSettings = S['MethodSettings'];

/** Порядок вкладок — порядок таблицы SPEC 7.5 (пользователи и календарь — отдельные пункты меню). */
export const DICTS = [
  'phases',
  'disciplines',
  'node-types',
  'profiles',
  'method',
  'ratios',
  'tags',
  'currencies',
  'vat-rates',
  'loss-reasons',
] as const;
export type DictKey = (typeof DICTS)[number];

export const isDictKey = (s: string): s is DictKey => (DICTS as readonly string[]).includes(s);
export const dictPath = (k: DictKey) => `/admin/dictionaries/${k}`;
export const dictKey = (k: DictKey) => ['admin', 'dict', k] as const;

export const HEX_RE = /^#[0-9A-Fa-f]{6}$/;
export const CODE_RE = /^[A-Z]{3}$/;
// два простых выражения вместо одного с необязательной группой (security/detect-unsafe-regex)
const INT_RE = /^\d{1,5}$/;
const FRACTION_RE = /^\d{1,5}[.,]\d{1,2}$/;
const number = (s: string) => INT_RE.test(s.trim()) || FRACTION_RE.test(s.trim());

/** Ввод с запятой — в формат API с точкой. */
export const decimal = (s: string) => s.trim().replace(',', '.');
/** Значение API для проверенного ввода. */
export const dec = (s: string) => asDecimalString(decimal(s));
/** Процент: 0–100, до двух знаков после запятой. */
export const pctValid = (s: string) => number(s) && Number(decimal(s)) <= 100;
/** Часы O/R/P нормы: до 99 999,5 и двух знаков. */
export const hoursValid = (s: string) => number(s) && Number(decimal(s)) <= 99999.5;

export type Pill = 'system' | 'crossCutting' | 'default';
export type Locks = {
  pill: Pill | null;
  /** Почему удалить нельзя (ключ подсказки) или null. */
  noDelete: string | null;
  noDeactivate: string | null;
};

const FREE: Locks = { pill: null, noDelete: null, noDeactivate: null };

/** Сквозная фаза одна: снять признак можно, только отметив другую фазу. */
export const phaseLocks = (p: Phase): Locks =>
  p.is_cross_cutting ? { pill: 'crossCutting', noDelete: 'crossCutting', noDeactivate: 'crossCutting' } : FREE;

/** «Работа» — тип по умолчанию: не удаляется и не отключается. */
export const nodeTypeLocks = (t: NodeType): Locks =>
  t.is_system ? { pill: 'system', noDelete: 'workType', noDeactivate: 'workType' } : FREE;

/** Профиль по умолчанию дисциплины не удаляют: сначала назначают другой в карточке дисциплины. */
export const profileLocks = (p: Profile, disciplines: readonly Discipline[]): Locks =>
  disciplines.some((d) => d.default_profile_id === p.id)
    ? { pill: 'default', noDelete: 'defaultProfile', noDeactivate: 'defaultProfile' }
    : FREE;

export const currencyLocks = (c: Currency): Locks =>
  c.code === 'RUB' ? { pill: 'system', noDelete: 'rub', noDeactivate: 'rub' } : FREE;

/** «Без НДС» неудаляема; ставка «по умолчанию» одна — снимают, отметив другую. */
export const vatLocks = (v: VatRate): Locks => {
  if (v.percent === null)
    return { pill: v.is_default ? 'default' : 'system', noDelete: 'noVat', noDeactivate: 'noVat' };
  return v.is_default ? { pill: 'default', noDelete: 'defaultVat', noDeactivate: 'defaultVat' } : FREE;
};

/** Профили дисциплины — для выбора профиля по умолчанию. */
export const profilesOf = (profiles: readonly Profile[], disciplineId: string) =>
  profiles.filter((p) => p.discipline_id === disciplineId);

/** Цепочка типов профиля словами: «Модуль → Функция». */
export const chainText = (chain: readonly string[], types: readonly NodeType[]) =>
  chain.map((id) => types.find((t) => t.id === id)?.name ?? '?').join(' → ');

export const byName = <T extends { name: string }>(items: readonly T[], q: string) => {
  const s = q.trim().toLocaleLowerCase('ru');
  return s ? items.filter((i) => i.name.toLocaleLowerCase('ru').includes(s)) : [...items];
};
