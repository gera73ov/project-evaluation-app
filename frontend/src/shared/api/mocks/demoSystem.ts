/**
 * FE-060 · раздел «Система» в демо: состояние служб (FR-SA-07), учётки администраторов,
 * суперадминистраторов и аудиторов ИБ, разделы настроек по умолчанию из settings.schema.json.
 * LDAP в списке нет: моки работают в режиме входа «Приложение».
 * Значения раздела отдаются по полным ключам (`security.mfa_policy`), секреты — `{"set": true}`.
 */
import settingsSchema from "../../../../../contracts/settings.schema.json";
import { PERSONAS } from "./personas";
import { NOW, minutesAgo, uuidFrom } from "./ids";

const checked = minutesAgo(1);

export function health() {
  return {
    app_version: "1.0.0-rc.3",
    schema_version: "0042_stage2",
    components: [
      {
        name: "db",
        ok: true,
        detail: "PostgreSQL 16.4, 12 мс",
        checked_at: checked,
      },
      { name: "redis", ok: true, detail: "7.2, 2 мс", checked_at: checked },
      {
        name: "smtp",
        ok: true,
        detail: "mail.corp.local:587, STARTTLS",
        checked_at: checked,
      },
      {
        name: "siem",
        ok: true,
        detail: "syslog TLS, очередь пуста",
        checked_at: checked,
      },
      {
        name: "queue",
        ok: true,
        detail: "в очереди 0, ошибок за сутки 0",
        checked_at: checked,
      },
      {
        name: "backup",
        ok: true,
        detail: "последняя копия 05.11.2026 02:00",
        checked_at: checked,
      },
      {
        name: "audit_chain",
        ok: true,
        detail: "цепочка хэшей цела",
        checked_at: checked,
      },
      {
        name: "audit_purge",
        ok: true,
        detail: "следующий запуск сегодня в 03:00",
        checked_at: checked,
      },
    ],
  };
}

type Role = "superadmin" | "admin" | "security_auditor";
type Account = {
  id: string;
  login: string;
  full_name: string;
  email: string | null;
  roles: Role[];
  status: "active" | "blocked" | "pending_password";
  totp_enabled: boolean;
  last_login_at: string | null;
};

function seedAccounts(): Account[] {
  const seed: [string, string, Role, Account["status"]][] = [
    [
      PERSONAS.superadmin.login,
      PERSONAS.superadmin.fullName,
      "superadmin",
      "active",
    ],
    ["sa.petrova", "С. Петрова", "superadmin", "active"],
    [PERSONAS.admin.login, PERSONAS.admin.fullName, "admin", "active"],
    ["v.blinov", "В. Блинов", "admin", "blocked"],
    [
      PERSONAS.auditor.login,
      PERSONAS.auditor.fullName,
      "security_auditor",
      "active",
    ],
  ];
  return seed.map(([login, name, role, status], i) => ({
    id: uuidFrom("user", login),
    login,
    full_name: name,
    email: `${login}@corp.local`,
    roles: [role],
    status,
    totp_enabled: true,
    last_login_at: i === 0 ? NOW : minutesAgo(60 * 24 * (i + 1)),
  }));
}

/** FE-063 · учётки раздела «Суперадминистраторы и администраторы», «Аудиторы ИБ» (FR-SA-05). */
let accounts = seedAccounts();
let anonymized = 0;
/** CR-010 · когда учётка раздела «Система» заблокирована (для списка «Анонимизация»). */
const blockedAt = new Map<string, string>();
const seedBlocked = () => {
  blockedAt.clear();
  blockedAt.set(uuidFrom("user", "v.blinov"), minutesAgo(60 * 24 * 30));
};
seedBlocked();
const anonymizedIds = new Set<string>();

/** Номер для «Удалённый пользователь #N» — общий для учёток «Системы» и пользователей. */
export function nextAnonymous(): number {
  anonymized += 1;
  return anonymized;
}

/** CR-010 · заблокированные или анонимизированные учётки раздела «Система». */
export function blockedOrAnonymized(status: "blocked" | "anonymized") {
  return accounts
    .filter(
      (a) =>
        a.status === "blocked" &&
        anonymizedIds.has(a.id) === (status === "anonymized"),
    )
    .map((a) => ({
      id: a.id,
      login: a.login,
      full_name: a.full_name,
      roles: [...a.roles],
      status,
      blocked_at: blockedAt.get(a.id) ?? null,
      last_login_at: a.last_login_at,
    }));
}

/** Первичная установка (FR-SA-01): есть только первый суперадминистратор. */
export function firstInstall() {
  accounts = seedAccounts().slice(0, 1);
}

export function admins() {
  return accounts.map((a) => ({ ...a, roles: [...a.roles] }));
}

const activeSuperadmins = () =>
  accounts.filter(
    (a) => a.status === "active" && a.roles.includes("superadmin"),
  );

export type AccountError =
  | "ALREADY_EXISTS"
  | "SUPERADMIN_LIMIT"
  | "LAST_SUPERADMIN"
  | "ROLE_INCOMPATIBLE"
  | "USER_NOT_BLOCKED"
  | "NOT_FOUND"
  | "VALIDATION_FAILED";

/** Ссылка активации: почта настроена — письмо, ссылку не показываем (FR-AUTH-LOC-01). */
function activation() {
  return {
    emailed: true,
    activation_url: null,
    expires_at: new Date(Date.parse(NOW) + 72 * 3600 * 1000).toISOString(),
  };
}

export function createAdmin(
  body: unknown,
): { error: AccountError } | ReturnType<typeof activation> {
  const b = new Map(
    Object.entries(body && typeof body === "object" ? body : {}),
  );
  const login = String(b.get("login") ?? "").trim();
  const role = b.get("role") as Role | undefined;
  // без тела (проверка моков по контракту) — ответ без создания учётки
  if (!login || !role) return activation();
  if (accounts.some((a) => a.login === login))
    return { error: "ALREADY_EXISTS" };
  if (
    role === "superadmin" &&
    accounts.filter(
      (a) => a.status !== "blocked" && a.roles.includes("superadmin"),
    ).length >= 3
  )
    return { error: "SUPERADMIN_LIMIT" };
  accounts.push({
    id: uuidFrom("user", login),
    login,
    full_name: String(b.get("full_name") ?? login),
    email: String(b.get("email") ?? "") || null,
    roles: [role],
    status: "pending_password",
    totp_enabled: false,
    last_login_at: null,
  });
  return activation();
}

export function patchAdmin(
  id: string,
  body: unknown,
): { error: AccountError } | Account {
  const a = accounts.find((x) => x.id === id);
  if (!a) return { error: "NOT_FOUND" };
  const b = new Map(
    Object.entries(body && typeof body === "object" ? body : {}),
  );
  const roles = b.get("roles") as Role[] | undefined;
  const status = b.get("status") as "active" | "blocked" | undefined;
  const lastSa =
    a.roles.includes("superadmin") &&
    a.status === "active" &&
    activeSuperadmins().length === 1;
  if (roles) {
    if (
      roles.length > 1 &&
      (roles.includes("superadmin") || roles.includes("security_auditor"))
    )
      return { error: "ROLE_INCOMPATIBLE" };
    if (lastSa && !roles.includes("superadmin"))
      return { error: "LAST_SUPERADMIN" };
    if (
      roles.includes("superadmin") &&
      !a.roles.includes("superadmin") &&
      activeSuperadmins().length >= 3
    )
      return { error: "SUPERADMIN_LIMIT" };
    a.roles = [...roles];
  }
  if (status) {
    if (status === "blocked" && lastSa) return { error: "LAST_SUPERADMIN" };
    if (status === "blocked" && a.status !== "blocked")
      blockedAt.set(a.id, NOW);
    if (status === "active") blockedAt.delete(a.id);
    a.status = status;
  }
  return { ...a, roles: [...a.roles] };
}

export function demoteAdmin(id: string): AccountError | null {
  const a = accounts.find((x) => x.id === id);
  if (!a) return "NOT_FOUND";
  if (
    a.roles.includes("superadmin") &&
    a.status === "active" &&
    activeSuperadmins().length === 1
  )
    return "LAST_SUPERADMIN";
  accounts = accounts.filter((x) => x.id !== id);
  return null;
}

export function resetCredentials(
  id: string,
): AccountError | ReturnType<typeof activation> {
  return accounts.some((a) => a.id === id) ? activation() : "NOT_FOUND";
}

/** SEC-PD-03: только заблокированного; ФИО → «Удалённый пользователь #N», логин и почта — случайные. */
export function anonymize(id: string): AccountError | null {
  const a = accounts.find((x) => x.id === id);
  if (!a) return "NOT_FOUND";
  if (a.status !== "blocked" || anonymizedIds.has(a.id))
    return "USER_NOT_BLOCKED";
  const n = nextAnonymous();
  anonymizedIds.add(a.id);
  a.full_name = `Удалённый пользователь #${n}`;
  a.login = `deleted-${uuidFrom("anon", String(n)).slice(0, 8)}`;
  a.email = null;
  a.totp_enabled = false;
  return null;
}

type SchemaProp = { default?: unknown; "x-secret"?: boolean };

const SCHEMA_PROPS = new Map(
  Object.entries(
    (settingsSchema as { properties: Record<string, SchemaProp> }).properties,
  ),
);

/**
 * FE-061, FE-062 · демо-значения поверх значений по умолчанию: почта и адрес ИБ заданы, каталог AD описан (как на макете
 * `sa-auth.png`), но режим входа — «Приложение», переход на AD ещё не выполнен.
 */
const SEED = new Map<string, unknown>([
  [
    "smtp.server",
    {
      host: "mail.corp.local",
      port: 587,
      security: "starttls",
      username: "svc-estimator",
      from_address: "estimator@corp.local",
      from_name: "Оценка проектов",
      timeout_seconds: 10,
    },
  ],
  ["security.alert_email", "ib@corp.local"],
  [
    "auth.ad.connection",
    {
      controllers: [
        { host: "dc1.corp.local", port: 636 },
        { host: "dc2.corp.local", port: 636 },
      ],
      protocol: "ldaps",
      ca_cert_pem:
        "-----BEGIN CERTIFICATE-----\nMIIDdemo\n-----END CERTIFICATE-----",
      base_dn: "OU=Users,DC=corp,DC=local",
      user_filter: "(&(objectClass=user)(sAMAccountName={login}))",
      login_attribute: "sAMAccountName",
      attr_full_name: "displayName",
      attr_email: "mail",
      attr_department: "department",
      bind_dn: "CN=svc-estimator,OU=Service,DC=corp,DC=local",
      timeout_seconds: 5,
    },
  ],
  [
    "auth.ad.access_groups",
    ["CN=APP-Estimator-Users,OU=Groups,DC=corp,DC=local"],
  ],
  [
    "auth.ad.role_mapping",
    {
      enabled: false,
      mappings: [
        {
          group_dn: "CN=APP-Estimator-Moderators,OU=Groups,DC=corp,DC=local",
          role: "moderator",
        },
        {
          group_dn: "CN=APP-Estimator-Presale,OU=Groups,DC=corp,DC=local",
          role: "presale",
        },
      ],
    },
  ],
]);

/** Сохранённые в этой сессии значения (PUT /system/settings/{section}). */
const saved = new Map<string, unknown>();
/** Подтверждение step-up действует до этого момента (мс), SEC-AUTH-05. */
let stepUpUntil = 0;

export function resetDemoSystem() {
  saved.clear();
  stepUpUntil = 0;
  accounts = seedAccounts();
  anonymized = 0;
  anonymizedIds.clear();
  seedBlocked();
}

export const STEP_UP_MS = 5 * 60 * 1000;

/** POST /auth/step-up: подтверждение на 5 минут. */
export function stepUp() {
  stepUpUntil = Date.now() + STEP_UP_MS;
  return {
    mfa_passed: true,
    step_up_until: new Date(stepUpUntil).toISOString(),
  };
}

/** Критичное действие без свежего подтверждения получает 403 STEP_UP_REQUIRED. */
export function stepUpFresh(): boolean {
  return Date.now() < stepUpUntil;
}

/** Текущее значение ключа настроек (сохранённое, демо или по умолчанию). */
export function settingValue(key: string): unknown {
  if (saved.has(key)) return saved.get(key);
  if (SEED.has(key)) return SEED.get(key);
  return SCHEMA_PROPS.get(key)?.default ?? null;
}

/** Раздел настроек: значения по умолчанию из settings.schema.json, секреты скрыты. */
export function settings(section: string) {
  const values: Record<string, unknown> = {};
  for (const [key, prop] of SCHEMA_PROPS) {
    if (!key.startsWith(`${section}.`)) continue;
    values[key] = prop["x-secret"] ? { set: true } : settingValue(key);
  }
  return { section, values };
}

/** Значения ключей (для шагов мастера первичной настройки), секреты скрыты. */
export function settingValues(keys: readonly string[]) {
  const values: Record<string, unknown> = {};
  for (const key of keys) {
    const prop = SCHEMA_PROPS.get(key);
    if (!prop) continue;
    values[key] = prop["x-secret"]
      ? saved.has(key)
        ? { set: true }
        : null
      : settingValue(key);
  }
  return values;
}

/**
 * Запись раздела: только ключи этого раздела; секрет `{"set": true}` значит «не менять».
 * Ключи, которые ведёт приложение (`x-owner: system`), клиент не пишет.
 */
export function saveSettings(section: string, values: unknown) {
  const entries =
    values && typeof values === "object" ? Object.entries(values) : [];
  for (const [key, value] of entries) {
    const prop = SCHEMA_PROPS.get(key) as
      | (SchemaProp & { "x-owner"?: string })
      | undefined;
    if (!prop || !key.startsWith(`${section}.`)) continue;
    if (prop["x-owner"] === "system") continue;
    if (prop["x-secret"]) {
      if (typeof value === "string" && value) saved.set(key, true);
      continue;
    }
    saved.set(key, value);
  }
  return settings(section);
}

/** Ключ без проверки раздела: переход на AD меняет `auth.mode`. */
export function setSetting(key: string, value: unknown) {
  saved.set(key, value);
}

/**
 * «Пороги и проценты» (GAP-13): ключи method.* без префикса, значения по умолчанию из
 * settings.schema.json; часы — в формате HoursString.
 */
export function methodSettings() {
  const values = new Map(Object.entries(settings("method").values));
  const large = values.get("method.large_leaf_hours") as {
    medium: number;
    detailed: number;
  };
  const out: Record<string, unknown> = {};
  for (const [key, value] of values) out[key.replace(/^method\./, "")] = value;
  out.large_leaf_hours = {
    medium: Number(large.medium).toFixed(2),
    detailed: Number(large.detailed).toFixed(2),
  };
  out.pm_percent_default = String(out.pm_percent_default);
  return out;
}

// --- CR-009 · тестовое письмо (7.1 шаг 2, FR-NOTIF-02) ------------------------------------

type SmtpServer = { host: string; port: number; username: string | null };

/**
 * Письмо с несохранёнными параметрами формы; без них — с сохранёнными. Сохранённый пароль
 * подставляется, только если host, port и username те же, иначе нужен smtp.password (422).
 */
export function smtpTest(
  body: unknown,
):
  | { error: "VALIDATION_FAILED" }
  | { ok: boolean; elapsed_ms: number; detail: string | null } {
  const b = new Map(
    Object.entries(body && typeof body === "object" ? body : {}),
  );
  const to = b.get("to");
  // пустое тело (проверка моков по схеме) — образец ответа
  if (to === undefined) return { ok: true, elapsed_ms: 0, detail: null };
  if (typeof to !== "string" || !/^[^@\s]+@[^@\s]+$/.test(to))
    return { error: "VALIDATION_FAILED" };
  const values = b.get("values");
  const v = new Map(
    Object.entries(values && typeof values === "object" ? values : {}),
  );
  const saved = settingValue("smtp.server") as SmtpServer;
  const server = (v.get("smtp.server") as SmtpServer | undefined) ?? saved;
  const samePlace =
    server.host === saved.host &&
    server.port === saved.port &&
    (server.username ?? null) === (saved.username ?? null);
  if (!samePlace && typeof v.get("smtp.password") !== "string")
    return { error: "VALIDATION_FAILED" };
  if (server.host.includes("old"))
    return {
      ok: false,
      elapsed_ms: 10000,
      detail: `${server.host}:${server.port}: нет ответа за 10 с`,
    };
  return {
    ok: true,
    elapsed_ms: 420,
    detail: `Письмо принято сервером ${server.host}`,
  };
}
