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

/** Раздел настроек: значения по умолчанию из settings.schema.json, секреты скрыты. */
export function settings(section: string) {
  const props = new Map(
    Object.entries(
      (settingsSchema as { properties: Record<string, SchemaProp> }).properties,
    ),
  );
  const values: Record<string, unknown> = {};
  for (const [key, prop] of props) {
    if (!key.startsWith(`${section}.`)) continue;
    values[key] = prop["x-secret"] ? { set: true } : (prop.default ?? null);
  }
  return { section, values };
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
