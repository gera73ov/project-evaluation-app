/**
 * FE-001 · пример значения по JSON-схеме контракта — для операций, у которых нет
 * собственных демо-данных (data.ts). Значения детерминированы: один и тот же путь в схеме
 * даёт один и тот же ответ.
 *
 * SEC-AUTHZ-04: свойство, схема которого — `*Money`, выводится только при `money: true`;
 * без права денег ключа в ответе нет совсем.
 */
import { resolveRef, type Schema } from './contract';
import { NOW, TODAY, uuidFrom } from './ids';

export type SampleOptions = { money: boolean };
/** strictPatterns: false — для pattern без примера вернуть пустую строку (поле заменят). */
export type SampleFlags = { strictPatterns?: boolean };

const MAX_DEPTH = 8;

/** Значения для шаблонов `pattern` контрактов: первый подходящий. */
const PATTERN_CANDIDATES = [
  '1',
  '1.00',
  '1000',
  'RUB',
  '#4a7bd0',
  'i.ivanov',
  '2026-11',
  '123456',
  '12345678',
];

export function isMoneyRef(schema: Schema | undefined): boolean {
  if (!schema) return false;
  if (schema.$ref?.endsWith('Money')) return true;
  return [...(schema.anyOf ?? []), ...(schema.oneOf ?? [])].some(isMoneyRef);
}

function deref(schema: Schema): Schema {
  let s = schema;
  for (let i = 0; s.$ref && i < 20; i += 1) s = { ...resolveRef(s.$ref), ...omitRef(s) };
  return s;
}

function omitRef(schema: Schema): Schema {
  const rest = { ...schema };
  delete rest.$ref;
  return rest;
}

function pickVariant(variants: Schema[]): Schema {
  return (
    variants.find((v) => {
      const d = deref(v);
      return d.type !== 'null' && !(Array.isArray(d.type) && d.type.every((t) => t === 'null'));
    }) ??
    variants[0] ??
    {}
  );
}

function stringValue(schema: Schema, path: string, flags: SampleFlags): string {
  switch (schema.format) {
    case 'uuid':
      return uuidFrom('sample', path);
    case 'date-time':
      return NOW;
    case 'date':
      return TODAY;
    case 'email':
      return 'user@example.test';
    case 'uri':
      return 'https://estimator.local/mock';
    case 'binary':
      return '';
    case 'time':
      return '09:00:00';
    default:
      break;
  }
  if (schema.pattern) {
    const re = new RegExp(schema.pattern, 'u');
    const hit = PATTERN_CANDIDATES.find((c) => re.test(c));
    if (hit === undefined && flags.strictPatterns === false) return '';
    if (hit === undefined)
      throw new Error(`моки: нет примера для pattern ${schema.pattern} (${path})`);
    return hit;
  }
  const base = 'Пример';
  const min = schema.minLength ?? 0;
  const max = schema.maxLength ?? Infinity;
  return base.padEnd(min, '.').slice(0, Math.max(min, Math.min(max, base.length)));
}

/** Пример значения для схемы. `path` — место в ответе, из него получаются стабильные UUID. */
export function sample(
  schema: Schema,
  options: SampleOptions,
  path = '$',
  depth = 0,
  flags: SampleFlags = {},
): unknown {
  const s = deref(schema);
  if (s.const !== undefined) return s.const;
  if (s.enum) return s.enum[0];
  if (s.allOf) {
    return Object.assign(
      {},
      ...s.allOf.map((part, i) => sample(part, options, `${path}&${i}`, depth, flags) as object),
    );
  }
  if (s.anyOf || s.oneOf)
    return sample(pickVariant(s.anyOf ?? s.oneOf ?? []), options, path, depth, flags);

  const type = Array.isArray(s.type) ? (s.type.find((t) => t !== 'null') ?? 'null') : s.type;
  switch (type) {
    case 'null':
      return null;
    case 'string':
      return stringValue(s, path, flags);
    case 'integer':
    case 'number':
      return Math.min(Math.max(s.minimum ?? 1, 1), s.maximum ?? Infinity);
    case 'boolean':
      return false;
    case 'array': {
      const count = depth >= MAX_DEPTH ? (s.minItems ?? 0) : Math.max(s.minItems ?? 0, 1);
      const n = Math.min(count, s.maxItems ?? Infinity);
      return Array.from({ length: n }, (_, i) =>
        sample(s.items ?? {}, options, `${path}[${i}]`, depth + 1, flags),
      );
    }
    default: {
      if (!s.properties) return {};
      const required = new Set(s.required ?? []);
      const out: Record<string, unknown> = {};
      for (const [key, prop] of Object.entries(s.properties)) {
        if (isMoneyRef(prop) && !options.money) continue;
        if (depth >= MAX_DEPTH && !required.has(key)) continue;
        out[key] = sample(prop, options, `${path}.${key}`, depth + 1, flags);
      }
      return out;
    }
  }
}

/**
 * Убрать из готовых данных денежные ключи по схеме (для демо-данных data.ts): ключ, схема
 * которого `*Money`, удаляется, если у пользователя нет права денег.
 */
export function stripMoney(schema: Schema, value: unknown, options: SampleOptions): unknown {
  if (options.money || value === null || typeof value !== 'object') return value;
  const s = deref(schema);
  if (s.anyOf || s.oneOf) {
    const variant = pickVariant(s.anyOf ?? s.oneOf ?? []);
    return stripMoney(variant, value, options);
  }
  if (Array.isArray(value)) return value.map((v) => stripMoney(s.items ?? {}, v, options));
  if (!s.properties) return value;
  const out: Record<string, unknown> = {};
  for (const [key, v] of Object.entries(value)) {
    const prop = s.properties[key];
    if (isMoneyRef(prop)) continue;
    out[key] = prop ? stripMoney(prop, v, options) : v;
  }
  return out;
}
