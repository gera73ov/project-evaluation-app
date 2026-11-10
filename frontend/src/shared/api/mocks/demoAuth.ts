/**
 * FE-061 · способ входа и Active Directory в демо (SPEC 11.2 №2–6, FR-AUTH-AD-03, FR-AUTH-SW-01):
 * «Проверить подключение» и «Проверить вход» с ответами каталога, отчёт перехода
 * «Приложение → AD» (сопоставлено / неоднозначно / не найдено), решения по неоднозначным и сам
 * переход. Сохранение настроек AD требует обеих проверок после последнего изменения.
 */
import { PEOPLE } from "./data";
import { NOW, uuidFrom } from "./ids";
import { PERSONAS } from "./personas";
import { setSetting, settingValue } from "./demoSystem";

type Json = Record<string, unknown>;

/** Проверки после последнего изменения параметров (FR-AUTH-AD-03). */
const checks = { connection: false, login: false };
/** Решения суперадминистратора: user_id → object_guid или null («не сопоставлять»). */
const decisions = new Map<string, string | null>();
/** CR-009 · итог последнего перехода «Приложение → AD» (getLastSwitch). */
type LastSwitch = {
  at: string;
  by: { id: string; full_name: string; initials: string; is_active: boolean };
  resolved: number;
  report: ReturnType<typeof report>;
};
let last: LastSwitch | null = null;

export function resetDemoAuth() {
  checks.connection = false;
  checks.login = false;
  decisions.clear();
  last = null;
}

export function lastSwitch(): LastSwitch | null {
  return last;
}

const AD_KEYS = [
  "auth.ad.connection",
  "auth.ad.access_groups",
  "auth.ad.role_mapping",
] as const;

const valuesOf = (body: unknown): unknown =>
  body && typeof body === "object"
    ? new Map(Object.entries(body)).get("values")
    : undefined;

/** Значение ключа из несохранённых `values` формы, иначе сохранённое. */
function formValue(values: unknown, key: string): unknown {
  const v =
    values && typeof values === "object"
      ? new Map(Object.entries(values)).get(key)
      : undefined;
  return v === undefined ? settingValue(key) : v;
}

/**
 * CR-009 · сохранённый пароль сервисной учётки уходит только на тот же сервер и с той же учёткой
 * bind: если в `values` они другие, а нового пароля нет — проверка не выполняется (422).
 */
export function needsBindPassword(body: unknown): boolean {
  const values = valuesOf(body);
  if (!values || typeof values !== "object") return false;
  const map = new Map(Object.entries(values));
  if (typeof map.get("auth.ad.bind_password") === "string") return false;
  const next = connectionOf(values);
  const saved = settingValue("auth.ad.connection") as Json;
  return (
    JSON.stringify(next.controllers) !== JSON.stringify(saved.controllers) ||
    next.bind_dn !== saved.bind_dn
  );
}

function connectionOf(values: unknown): Json {
  const v =
    values && typeof values === "object"
      ? new Map(Object.entries(values)).get("auth.ad.connection")
      : undefined;
  return (
    v && typeof v === "object" ? v : settingValue("auth.ad.connection")
  ) as Json;
}

export function testConnection(body: unknown) {
  const conn = connectionOf(valuesOf(body));
  const controllers = Array.isArray(conn.controllers)
    ? (conn.controllers as { host: string; port: number }[])
    : [];
  checks.connection = false;
  if (controllers.length === 0)
    return {
      ok: false,
      elapsed_ms: 0,
      detail: "Не указан ни один контроллер",
      user: null,
    };
  if (!conn.base_dn || !conn.bind_dn)
    return {
      ok: false,
      elapsed_ms: 0,
      detail: "Заполните Base DN и сервисную учётку",
      user: null,
    };
  const first = controllers[0] as { host: string; port: number };
  if (first.host.includes("old"))
    return {
      ok: false,
      elapsed_ms: 5000,
      detail: `${first.host}: нет ответа за 5 с`,
      user: null,
    };
  checks.connection = true;
  return {
    ok: true,
    elapsed_ms: 200,
    detail: `Подключено к ${first.host}`,
    user: null,
  };
}

const USERS = "CN=APP-Estimator-Users,OU=Groups,DC=corp,DC=local";
const MODS = "CN=APP-Estimator-Moderators,OU=Groups,DC=corp,DC=local";

/** Учётки каталога для «Проверить вход». */
const DIRECTORY = new Map([
  [
    "i.ivanov",
    {
      full_name: "Иванов Иван Иванович",
      email: "i.ivanov@corp.ru",
      disabled: false,
      groups: [USERS, MODS],
    },
  ],
  [
    "k.belova",
    {
      full_name: "Белова Ксения Андреевна",
      email: "k.belova@corp.ru",
      disabled: false,
      groups: ["CN=Sales,OU=Groups,DC=corp,DC=local"],
    },
  ],
  [
    "v.sokolov",
    {
      full_name: "Соколов Виктор Петрович",
      email: "v.sokolov@corp.ru",
      disabled: true,
      groups: [USERS],
    },
  ],
]);

/** FE-070 · ещё учётки каталога для «Найти в AD»: заведены заранее не все. */
const MORE = new Map([
  [
    "a.volkova",
    {
      full_name: "Волкова Анна Сергеевна",
      email: "a.volkova@corp.ru",
      disabled: false,
      groups: [USERS],
    },
  ],
  [
    "a.volkov",
    {
      full_name: "Волков Алексей Игоревич",
      email: "a.volkov@corp.ru",
      disabled: false,
      groups: [USERS, MODS],
    },
  ],
]);

const DEPARTMENTS = new Map([
  ["i.ivanov", "Отдел разработки"],
  ["a.volkova", "Отдел аналитики"],
  ["a.volkov", "Отдел разработки"],
  ["k.belova", "Коммерческий отдел"],
]);

export type DirectoryEntry = {
  object_guid: string;
  login: string;
  full_name: string;
  email: string;
  department: string | null;
  in_access_group: boolean;
  disabled: boolean;
  roles: ("moderator" | "presale")[];
};

/** FE-070 · «Найти в AD»: по логину или ФИО, от 3 символов, не больше 50 (FR-AUTH-AD-10). */
export function searchDirectory(q: string): DirectoryEntry[] {
  const needle = q.trim().toLowerCase();
  if (needle.length < 3) return [];
  return [...DIRECTORY, ...MORE]
    .filter(
      ([login, e]) =>
        login.includes(needle) || e.full_name.toLowerCase().includes(needle),
    )
    .slice(0, 50)
    .map(([login, e]) => directoryEntry(login, e));
}

export function directoryByGuid(guid: string): DirectoryEntry | null {
  for (const [login, e] of [...DIRECTORY, ...MORE]) {
    if (uuidFrom("ad", login) === guid) return directoryEntry(login, e);
  }
  return null;
}

function directoryEntry(
  login: string,
  e: { full_name: string; email: string; disabled: boolean; groups: string[] },
): DirectoryEntry {
  return {
    object_guid: uuidFrom("ad", login),
    login,
    full_name: e.full_name,
    email: e.email,
    department: DEPARTMENTS.get(login) ?? null,
    in_access_group: e.groups.includes(USERS),
    disabled: e.disabled,
    roles: rolesOf(e.groups),
  };
}

export type RoleMapping = {
  enabled: boolean;
  mappings: { group_dn: string; role: "moderator" | "presale" }[];
};

/** Роли по группам, если сопоставление включено (только «Модератор» и «Пресейл»). */
export function rolesOf(
  groups: string[],
  mapping = settingValue("auth.ad.role_mapping") as RoleMapping,
) {
  if (!mapping.enabled) return [];
  return [
    ...new Set(
      mapping.mappings
        .filter((m) => groups.includes(m.group_dn))
        .map((m) => m.role),
    ),
  ];
}

export function testLogin(body: unknown) {
  const b = new Map(
    Object.entries(body && typeof body === "object" ? body : {}),
  );
  const login = String(b.get("login") ?? "").trim();
  const password = String(b.get("password") ?? "");
  checks.login = false;
  const found = DIRECTORY.get(login);
  if (!found || password === "wrong")
    return {
      ok: false,
      elapsed_ms: 180,
      detail: "Пользователь не найден или пароль неверный",
      user: null,
    };
  // CR-009: группа доступа и сопоставление ролей — из несохранённой формы, если она передана
  const values = valuesOf(body);
  const access = formValue(values, "auth.ad.access_groups") as string[];
  const mapping = formValue(values, "auth.ad.role_mapping") as RoleMapping;
  const user = {
    ...found,
    groups: found.groups.map((g) => g.replace(/^CN=([^,]+),.*$/, "$1")),
    roles: rolesOf(found.groups, mapping),
    in_access_group: found.groups.some((g) => access.includes(g)),
  };
  // вход прошёл, если учётка активна и в группе доступа (FR-AUTH-AD-05)
  const ok = !found.disabled && user.in_access_group;
  checks.login = ok;
  return { ok, elapsed_ms: 240, detail: null, user };
}

/**
 * Сохранение раздела auth: если параметры AD меняются, нужны обе проверки после изменения,
 * иначе — список недостающих (`missing`). После сохранения проверки нужно пройти заново.
 */
export function missingChecks(values: unknown): string[] {
  const next = new Map(
    Object.entries(values && typeof values === "object" ? values : {}),
  );
  const changed =
    AD_KEYS.some(
      (key) =>
        next.has(key) &&
        JSON.stringify(next.get(key)) !== JSON.stringify(settingValue(key)),
    ) || typeof next.get("auth.ad.bind_password") === "string";
  if (!changed) return [];
  return [
    ...(checks.connection ? [] : ["connection"]),
    ...(checks.login ? [] : ["login"]),
  ];
}

/** Обе проверки пройдены после последнего изменения (шаг 3 мастера, режим AD). */
export function checksMissing(): string[] {
  return [
    ...(checks.connection ? [] : ["connection"]),
    ...(checks.login ? [] : ["login"]),
  ];
}

export function afterSave() {
  checks.connection = false;
  checks.login = false;
  setSetting("auth.ad.verification", {
    params_sha256: "demo",
    connection_ok_at: NOW,
    login_ok_at: NOW,
  });
}

// --- переход «Приложение → AD» -----------------------------------------------------------

type Candidate = {
  user_id: string;
  login: string;
  full_name: string;
  ad_candidates: { object_guid: string; login: string; full_name: string }[];
};

function local(
  login: string,
  fullName: string,
  ad: [string, string][],
): Candidate {
  return {
    user_id: uuidFrom("user", login),
    login,
    full_name: fullName,
    ad_candidates: ad.map(([l, name]) => ({
      object_guid: uuidFrom("ad", l),
      login: l,
      full_name: name,
    })),
  };
}

/** Локальные учётки (кроме суперадминистраторов) и их совпадения в каталоге. */
function candidates(): Candidate[] {
  const p = PERSONAS;
  return [
    local(p.expert.login, p.expert.fullName, [
      ["i.ivanov", "Иванов Иван Иванович"],
    ]),
    local(p.moderator.login, p.moderator.fullName, [
      ["a.smirnova", "Смирнова Анна Сергеевна"],
    ]),
    local(p.presale.login, p.presale.fullName, [
      ["p.sidorov", "Сидоров Павел Олегович"],
    ]),
    local(p.admin.login, p.admin.fullName, [["a.admin", "Админов Алексей"]]),
    local(PEOPLE.kuznetsova.login, PEOPLE.kuznetsova.fullName, [
      ["o.kuznetsova", "Кузнецова Ольга Игоревна"],
    ]),
    local(PEOPLE.orlova.login, PEOPLE.orlova.fullName, [
      ["m.orlova", "Орлова Мария Викторовна"],
      ["m.orlova2", "Орлова Марина Сергеевна"],
    ]),
    local(PEOPLE.novikov.login, PEOPLE.novikov.fullName, [
      ["n.novikov", "Новиков Никита Андреевич"],
      ["n.novikov.ext", "Новиков Николай (подрядчик)"],
    ]),
    local(PEOPLE.petrov.login, PEOPLE.petrov.fullName, []),
    local(PEOPLE.morozov.login, PEOPLE.morozov.fullName, []),
  ];
}

function report(applied: boolean) {
  const matched: Candidate[] = [];
  const ambiguous: Candidate[] = [];
  const notFound: Candidate[] = [];
  for (const c of candidates()) {
    if (c.ad_candidates.length === 1) matched.push(c);
    else if (c.ad_candidates.length === 0) notFound.push(c);
    else if (!decisions.has(c.user_id)) ambiguous.push(c);
    else {
      const guid = decisions.get(c.user_id);
      const pick = c.ad_candidates.filter((a) => a.object_guid === guid);
      if (pick.length) matched.push({ ...c, ad_candidates: pick });
      else notFound.push({ ...c, ad_candidates: [] });
    }
  }
  return { matched, ambiguous, not_found: notFound, applied };
}

export type SwitchOutcome =
  | { report: ReturnType<typeof report> }
  | { error: "MODE_SWITCH_NOT_ALLOWED" }
  | { error: "MODE_SWITCH_UNRESOLVED"; unresolved: number };

export function switchMode(
  body: unknown,
  by?: LastSwitch["by"],
): SwitchOutcome {
  const b = new Map(
    Object.entries(body && typeof body === "object" ? body : {}),
  );
  // без тела (проверка моков по контракту) — как dry run перехода на AD
  const mode = b.get("mode") ?? "ad";
  const dryRun = b.get("dry_run") !== false;
  if (mode !== "ad" || (!dryRun && settingValue("auth.mode") === "ad"))
    return { error: "MODE_SWITCH_NOT_ALLOWED" };
  const r = report(false);
  if (dryRun) return { report: r };
  if (r.ambiguous.length)
    return { error: "MODE_SWITCH_UNRESOLVED", unresolved: r.ambiguous.length };
  setSetting("auth.mode", "ad");
  const applied = { ...r, applied: true };
  if (by) last = { at: NOW, by, resolved: decisions.size, report: applied };
  return { report: applied };
}

export function resolve(body: unknown) {
  const b = new Map(
    Object.entries(body && typeof body === "object" ? body : {}),
  );
  const list = b.get("decisions");
  for (const d of Array.isArray(list) ? list : []) {
    const m = new Map(Object.entries(d as object));
    const id = m.get("user_id");
    const guid = m.get("object_guid");
    if (typeof id === "string")
      decisions.set(id, typeof guid === "string" ? guid : null);
  }
  return report(false);
}
