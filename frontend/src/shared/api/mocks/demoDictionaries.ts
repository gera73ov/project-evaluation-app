/**
 * FE-071 · справочники админки администратора (SPEC 7.5, BR-ADM-01): записи живут в памяти моков,
 * заполняются при первом обращении из демо-данных. Правила сервера (contracts/errors.yaml,
 * DICTIONARY_IN_USE): ровно одна сквозная фаза и одна ставка НДС «по умолчанию»; «Работа», RUB и
 * «Без НДС» не удаляются и не отключаются; записи демо-проектов не удаляются (IN_USE).
 */
import { uuidFrom } from "./ids";

export type Kind =
  | "phases"
  | "disciplines"
  | "node_types"
  | "profiles"
  | "ratios"
  | "tags"
  | "currencies"
  | "vat_rates"
  | "loss_reasons";

export type Rec = Record<string, unknown> & { is_active: boolean };
export type DictError =
  | { error: "NOT_FOUND" }
  | { error: "DICTIONARY_IN_USE" }
  | { error: "ALREADY_EXISTS" }
  | { error: "VALIDATION_FAILED"; field: string };

export const isError = (r: Rec | DictError): r is DictError =>
  typeof r.error === "string";

const stores = new Map<Kind, Rec[]>();
const used = new Map<Kind, Set<string>>();
let seeds: Map<Kind, () => Rec[]> = new Map();

/**
 * Записи демо-проектов используются в проектах — удалить их нельзя, только отключить. Валюты не
 * в списке: проверка моков удаляет USD и ждёт успеха.
 */
const IN_USE: readonly Kind[] = [
  "phases",
  "disciplines",
  "node_types",
  "profiles",
  "tags",
  "loss_reasons",
];

export function setSeeds(map: Record<Kind, () => Rec[]>) {
  seeds = new Map(Object.entries(map) as [Kind, () => Rec[]][]);
}

export function resetDemoDictionaries() {
  stores.clear();
  used.clear();
}

const keyOf = (kind: Kind, r: Rec) =>
  String(kind === "currencies" ? r.code : r.id);

function store(kind: Kind): Rec[] {
  let items = stores.get(kind);
  if (!items) {
    items = (seeds.get(kind)?.() ?? []).map((r) => ({ ...r }));
    stores.set(kind, items);
    used.set(
      kind,
      new Set(IN_USE.includes(kind) ? items.map((r) => keyOf(kind, r)) : []),
    );
  }
  return items;
}

export function list(kind: Kind, includeInactive = true): Rec[] {
  return store(kind).filter((r) => includeInactive || r.is_active);
}

export function find(kind: Kind, key: string): Rec | undefined {
  return store(kind).find((r) => keyOf(kind, r) === key);
}

const HEX = /^#[0-9A-Fa-f]{6}$/;
const CODE = /^[A-Z]{3}$/;
const text = (v: unknown, max: number) =>
  typeof v === "string" && v.trim() !== "" && v.trim().length <= max;
const INT = /^\d+$/;
const FRACTION = /^\d+\.\d+$/;
const pct = (v: unknown, max: number) =>
  typeof v === "string" &&
  (INT.test(v) || FRACTION.test(v)) &&
  Number(v) <= max;

/** Поле, которое не прошло проверку, или null. */
function invalid(kind: Kind, r: Rec): string | null {
  switch (kind) {
    case "phases":
      return text(r.name, 100) ? null : "name";
    case "disciplines":
      if (!text(r.name, 100)) return "name";
      if (!text(r.short_name, 12)) return "short_name";
      return HEX.test(String(r.color)) ? null : "color";
    case "node_types":
      if (!text(r.name, 50)) return "name";
      return Array.isArray(r.norms) && r.norms.length <= 20 ? null : "norms";
    case "profiles": {
      if (!find("disciplines", String(r.discipline_id))) return "discipline_id";
      if (!text(r.name, 100)) return "name";
      const chain = r.type_chain;
      return Array.isArray(chain) && chain.length >= 1 && chain.length <= 8
        ? null
        : "type_chain";
    }
    case "ratios": {
      const b = r.disciplines_b;
      if (!find("disciplines", String(r.discipline_a_id)))
        return "discipline_a_id";
      if (!Array.isArray(b) || b.length === 0 || b.includes(r.discipline_a_id))
        return "disciplines_b";
      if (!pct(r.min_pct, 100)) return "min_pct";
      return pct(r.max_pct, 100) && Number(r.max_pct) >= Number(r.min_pct)
        ? null
        : "max_pct";
    }
    case "tags":
      if (!text(r.name, 50)) return "name";
      if (!text(r.short_name, 12)) return "short_name";
      return HEX.test(String(r.color)) ? null : "color";
    case "currencies":
      if (!CODE.test(String(r.code))) return "code";
      return typeof r.symbol === "string" && r.symbol.length <= 8
        ? null
        : "symbol";
    case "vat_rates":
      if (!text(r.name, 50)) return "name";
      return r.percent === null || pct(r.percent, 100) ? null : "percent";
    case "loss_reasons":
      return text(r.name, 100) ? null : "name";
  }
}

/** Неудаляемая и неотключаемая запись (тип «Работа», RUB, «Без НДС»). */
export function isProtected(kind: Kind, r: Rec): boolean {
  if (kind === "node_types") return r.is_system === true;
  if (kind === "currencies") return r.code === "RUB";
  if (kind === "vat_rates") return r.percent === null;
  return false;
}

const DEFAULTS = new Map<Kind, Record<string, unknown>>([
  ["phases", { is_cross_cutting: false }],
  ["disciplines", { color: "#868e96", default_profile_id: null }],
  [
    "node_types",
    { icon: "work", norms: [], is_system: false, project_id: null },
  ],
  ["tags", { color: "#868e96", category: "tech" }],
  ["currencies", { symbol: "" }],
  ["vat_rates", { is_default: false }],
  ["loss_reasons", { is_other: false }],
]);

/** Сквозная фаза и ставка «по умолчанию» — ровно одна: новая отметка снимает прежнюю. */
const SINGLE = new Map<Kind, string>([
  ["phases", "is_cross_cutting"],
  ["vat_rates", "is_default"],
]);

function apply(kind: Kind, next: Rec, prev: Rec | undefined): DictError | null {
  const flag = SINGLE.get(kind);
  if (flag && prev?.[flag] === true && next[flag] !== true)
    return { error: "DICTIONARY_IN_USE" };
  if (flag && prev?.[flag] === true && !next.is_active)
    return { error: "DICTIONARY_IN_USE" };
  if (prev && isProtected(kind, prev) && !next.is_active)
    return { error: "DICTIONARY_IN_USE" };
  if (kind === "disciplines" && next.default_profile_id) {
    const profile = find("profiles", String(next.default_profile_id));
    if (!profile || profile.discipline_id !== next.id)
      return { error: "VALIDATION_FAILED", field: "default_profile_id" };
  }
  if (flag && next[flag] === true)
    for (const r of store(kind)) if (r !== prev) r[flag] = false;
  return null;
}

const WRITABLE = new Map<Kind, readonly string[]>([
  ["phases", ["name", "sort_order", "is_cross_cutting", "is_active"]],
  [
    "disciplines",
    ["name", "short_name", "color", "default_profile_id", "is_active"],
  ],
  ["node_types", ["name", "icon", "norms", "is_active"]],
  ["profiles", ["discipline_id", "name", "type_chain", "is_active"]],
  [
    "ratios",
    ["discipline_a_id", "disciplines_b", "min_pct", "max_pct", "is_active"],
  ],
  ["tags", ["name", "short_name", "color", "category", "is_active"]],
  ["currencies", ["code", "symbol", "is_active"]],
  ["vat_rates", ["name", "percent", "is_default", "is_active"]],
  ["loss_reasons", ["name", "is_other", "is_active"]],
]);

function pick(kind: Kind, body: unknown): Record<string, unknown> {
  const src = new Map(
    Object.entries(body && typeof body === "object" ? body : {}),
  );
  const out: Record<string, unknown> = {};
  for (const key of WRITABLE.get(kind) ?? [])
    if (src.has(key)) out[key] = src.get(key);
  return out;
}

const trimmed = (r: Rec) => {
  for (const key of ["name", "short_name", "symbol"])
    if (typeof r[key] === "string") r[key] = (r[key] as string).trim();
  return r;
};

/** Пустое тело (проверка моков) — undefined: ответ строится из примера схемы, данные не меняются. */
export function create(kind: Kind, body: unknown): Rec | DictError | undefined {
  const fields = pick(kind, body);
  if (Object.keys(fields).length === 0) return undefined;
  const items = store(kind);
  const order =
    kind === "phases"
      ? { sort_order: items.length + 1 }
      : ({} as Record<string, unknown>);
  const next = trimmed({
    ...(DEFAULTS.get(kind) ?? {}),
    ...order,
    is_active: true,
    ...fields,
  } as Rec);
  if (kind !== "currencies")
    next.id = uuidFrom("dict", kind, String(next.name), String(items.length));
  const field = invalid(kind, next);
  if (field) return { error: "VALIDATION_FAILED", field };
  if (kind === "currencies" && find(kind, String(next.code)))
    return { error: "ALREADY_EXISTS" };
  const err = apply(kind, next, undefined);
  if (err) return err;
  items.push(next);
  return next;
}

export function update(
  kind: Kind,
  key: string,
  body: unknown,
): Rec | DictError {
  const prev = find(kind, key);
  if (!prev) return { error: "NOT_FOUND" };
  const fields = pick(kind, body);
  if (kind === "currencies") delete fields.code;
  const next = trimmed({ ...prev, ...fields } as Rec);
  const field = invalid(kind, next);
  if (field) return { error: "VALIDATION_FAILED", field };
  const err = apply(kind, next, prev);
  if (err) return err;
  Object.assign(prev, next);
  return prev;
}

export function remove(kind: Kind, key: string): DictError | null {
  const items = store(kind);
  const r = find(kind, key);
  if (!r) return { error: "NOT_FOUND" };
  const flag = SINGLE.get(kind);
  const defaultProfile =
    kind === "profiles" &&
    list("disciplines").some((d) => d.default_profile_id === r.id);
  if (
    isProtected(kind, r) ||
    (flag && r[flag] === true) ||
    defaultProfile ||
    used.get(kind)?.has(key)
  )
    return { error: "DICTIONARY_IN_USE" };
  items.splice(items.indexOf(r), 1);
  return null;
}
