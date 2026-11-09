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

type Account = {
  login: string;
  full_name: string;
  roles: ("superadmin" | "admin" | "security_auditor")[];
};

const ACCOUNTS: Account[] = [
  {
    login: PERSONAS.superadmin.login,
    full_name: PERSONAS.superadmin.fullName,
    roles: ["superadmin"],
  },
  { login: "sa.petrova", full_name: "С. Петрова", roles: ["superadmin"] },
  {
    login: PERSONAS.admin.login,
    full_name: PERSONAS.admin.fullName,
    roles: ["admin"],
  },
  {
    login: PERSONAS.auditor.login,
    full_name: PERSONAS.auditor.fullName,
    roles: ["security_auditor"],
  },
];

export function admins() {
  return ACCOUNTS.map((a, i) => ({
    id: uuidFrom("user", a.login),
    login: a.login,
    full_name: a.full_name,
    email: `${a.login}@corp.local`,
    roles: a.roles,
    status: "active" as const,
    totp_enabled: true,
    last_login_at: i === 0 ? NOW : minutesAgo(60 * 24 * (i + 1)),
  }));
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
