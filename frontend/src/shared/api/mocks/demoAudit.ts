/**
 * FE-065 · журнал аудита в демо (SEC-AUD-06, Q-27): записи за последние дни по всем категориям
 * contracts/audit-events.yaml. Фильтры — период, пользователь, тип события, результат; страницы по
 * курсору. Администратор видит только «Пользователи и роли» и «Справочники».
 */
import { AUDIT_CATEGORIES, AUDIT_EVENTS } from "../generated/audit-events";
import { minutesAgo } from "./ids";
import { PERSONAS, personaId, type Persona } from "./personas";

type Result = "success" | "failure" | "denied";
type Who = keyof typeof PERSONAS | null;

/** [минут назад, событие, результат, кто, объект, детали] */
const SEED: [
  number,
  string,
  Result,
  Who,
  string | null,
  Record<string, unknown>,
][] = [
  [
    3,
    "auth.login.succeeded",
    "success",
    "auditor",
    "session",
    { method: "local", mfa: true },
  ],
  [8, "audit.viewed", "success", "auditor", "audit_log", {}],
  [
    15,
    "auth.login.failed",
    "failure",
    null,
    "user",
    { reason: "invalid_credentials", method: "local", step: "password" },
  ],
  [
    16,
    "auth.login.failed",
    "failure",
    null,
    "user",
    { reason: "invalid_credentials", method: "local", step: "password" },
  ],
  [
    22,
    "security.access_denied",
    "denied",
    "expert",
    "project",
    { permission: "money.read" },
  ],
  [
    40,
    "users.roles.changed",
    "success",
    "admin",
    "user",
    { added: ["moderator"], removed: [] },
  ],
  [
    55,
    "dict.changed",
    "success",
    "admin",
    "dictionary_item",
    { dictionary: "work_types", action: "create" },
  ],
  [
    70,
    "system.settings.changed",
    "success",
    "superadmin",
    "setting",
    { key: "security.session" },
  ],
  [95, "auth.step_up.passed", "success", "superadmin", "session", {}],
  [120, "users.blocked", "success", "admin", "user", {}],
  [
    180,
    "project.status.changed",
    "success",
    "moderator",
    "project",
    { from: "draft", to: "in_progress" },
  ],
  [
    240,
    "export.created",
    "success",
    "presale_head",
    "export",
    { kind: "portfolio_xlsx" },
  ],
  [300, "auth.logout", "success", "moderator", "session", {}],
  [
    420,
    "security.network_denied",
    "denied",
    null,
    null,
    { path: "/api/v1/system/settings" },
  ],
  [600, "auth.mfa.enrolled", "success", "presale", "user", {}],
  [900, "users.created", "success", "admin", "user", { role: "expert" }],
  [
    1300,
    "dict.changed",
    "success",
    "admin",
    "dictionary_item",
    { dictionary: "disciplines", action: "update" },
  ],
  [1500, "auth.lockout.pair_locked", "denied", null, "user", { minutes: 15 }],
  [2000, "project.created", "success", "moderator", "project", {}],
  [
    2900,
    "system.privileged_account.changed",
    "success",
    "superadmin",
    "user",
    { action: "create", role: "superadmin" },
  ],
  [3500, "audit.exported", "success", "auditor", "audit_log", { rows: 1240 }],
  [4400, "auth.password.changed", "success", "expert", "user", {}],
  [
    5800,
    "users.updated",
    "failure",
    "admin",
    "user",
    { reason: "validation_failed" },
  ],
  [
    7200,
    "system.cli.executed",
    "success",
    null,
    "cli_command",
    { actor: "cli", os_user: "deploy", command: "issue-activation" },
  ],
];

/** Ещё записи «вход/выход» за неделю — чтобы было что листать. */
function routine(): typeof SEED {
  const who: Who[] = [
    "expert",
    "moderator",
    "presale",
    "presale_head",
    "admin",
  ];
  const out: typeof SEED = [];
  for (let i = 0; i < 60; i++) {
    const p = who[i % who.length] ?? "expert";
    out.push([
      8000 + i * 120,
      i % 2 ? "auth.logout" : "auth.login.succeeded",
      "success",
      p,
      "session",
      i % 2 ? {} : { method: "local", mfa: true },
    ]);
  }
  return out;
}

const entries = [...SEED, ...routine()].map(
  ([ago, type, result, who, object, details], i) => {
    const p = who ? PERSONAS[who] : null;
    return {
      id: 100_000 - i,
      ts: minutesAgo(ago),
      event_type: type,
      category: AUDIT_EVENTS[type]?.category ?? "security",
      result,
      user_id: p ? personaId(p) : null,
      login: p ? p.login : type === "auth.login.failed" ? "admin1" : null,
      ip:
        type === "system.cli.executed"
          ? null
          : `10.10.${(i % 7) + 1}.${(i * 13) % 250}`,
      user_agent:
        type === "system.cli.executed"
          ? null
          : "Mozilla/5.0 (Windows NT 10.0) Chrome/130.0",
      object_type: object,
      object_id:
        object === "setting"
          ? String(details.key)
          : object
            ? `0190f0f0-0000-7000-8000-${String(i).padStart(12, "0")}`
            : null,
      details,
    };
  },
);

/** Категории, видимые роли (SEC-AUD-06): аудитор и суперадминистратор — все, администратор — две. */
function visibleCategories(persona: Persona): Set<string> {
  const roles = persona.systemRoles;
  return new Set(
    Object.entries(AUDIT_CATEGORIES)
      .filter(([, c]) => c.visible_to.some((r) => roles.includes(r)))
      .map(([k]) => k),
  );
}

export function list(persona: Persona, q: Record<string, string | undefined>) {
  const cats = visibleCategories(persona);
  const from = q.from ? Date.parse(q.from) : -Infinity;
  const to = q.to ? Date.parse(q.to) : Infinity;
  const rows = entries.filter(
    (e) =>
      cats.has(e.category) &&
      Date.parse(e.ts) >= from &&
      Date.parse(e.ts) <= to &&
      (!q.user_id || e.user_id === q.user_id) &&
      (!q.event_type || e.event_type === q.event_type) &&
      (!q.result || e.result === q.result),
  );
  const offset = Number(q.cursor ?? 0) || 0;
  const limit = Math.min(Math.max(Number(q.limit ?? 50) || 50, 1), 200);
  const page = rows.slice(offset, offset + limit);
  return {
    items: page,
    next_cursor: offset + limit < rows.length ? String(offset + limit) : null,
  };
}
