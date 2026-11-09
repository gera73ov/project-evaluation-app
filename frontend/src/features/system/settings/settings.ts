/**
 * FE-062 · общие правила форм раздела «Система» (ADM-000): границы чисел берутся из
 * contracts/settings.schema.json, чтобы форма и сервер проверяли одно и то же; значения раздела
 * приходят по полным ключам (`security.session`), секреты — `{"set": true}`.
 */
import schema from '../../../../../contracts/settings.schema.json';

type Prop = { type?: string | string[]; minimum?: number; maximum?: number; properties?: Record<string, Prop> };

const PROPS = new Map(Object.entries((schema as { properties: Record<string, Prop> }).properties));

/** Границы целого: `limits('security.session', 'idle_minutes_user')` → {min: 5, max: 480}. */
export function limits(key: string, field?: string): { min: number; max: number } {
  const top = PROPS.get(key);
  const prop = field ? new Map(Object.entries(top?.properties ?? {})).get(field) : top;
  return { min: prop?.minimum ?? 0, max: prop?.maximum ?? Number.MAX_SAFE_INTEGER };
}

/** Целое в границах ключа; null/пустое — ошибка, если поле обязательно. */
export function intError(value: number | null, key: string, field?: string): boolean {
  if (value === null) return true;
  const { min, max } = limits(key, field);
  return !Number.isInteger(value) || value < min || value > max;
}

export function valueOf<T>(values: object, key: string): T {
  return new Map(Object.entries(values)).get(key) as T;
}

/** Секрет задан на сервере (`{"set": true}`). */
export function secretSet(values: object, key: string): boolean {
  const v = valueOf<unknown>(values, key);
  return Boolean(v && typeof v === 'object' && new Map(Object.entries(v)).get('set') === true);
}

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
export const isEmail = (s: string) => s.length <= 254 && EMAIL.test(s);

/** CIDR IPv4 или IPv6: адрес по шаблону схемы и префикс не длиннее адреса. */
export function isCidr(text: string): boolean {
  const [addr = '', prefix, ...rest] = text.split('/');
  if (rest.length || prefix === undefined || !/^\d{1,3}$/.test(prefix) || text.length > 43) return false;
  const bits = Number(prefix);
  if (addr.includes(':')) return /^[0-9a-fA-F:.]+$/.test(addr) && bits <= 128;
  const parts = addr.split('.');
  return parts.length === 4 && parts.every((p) => /^\d{1,3}$/.test(p) && Number(p) <= 255) && bits <= 32;
}

/** Строки textarea → список без пустых и повторов. */
export function lines(text: string): string[] {
  return [
    ...new Set(
      text
        .split('\n')
        .map((s) => s.trim())
        .filter(Boolean),
    ),
  ];
}

/** «HH:MM» 00:00–23:59. */
export const isTime = (s: string) => /^([01]\d|2[0-3]):[0-5]\d$/.test(s);
