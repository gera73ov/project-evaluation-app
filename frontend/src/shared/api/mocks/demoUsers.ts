/**
 * FE-070 · пользователи админки администратора в демо (SPEC 7.5 «Пользователи», FR-AUTH-AD-10,
 * FR-ADM-05): список с поиском и фильтрами, создание (режим «Приложение» — по логину, AD — из
 * каталога), роли, блокировка, сбросы и «Заменить участника» во всех активных проектах.
 * Суперадминистраторы и аудиторы ИБ ведутся в разделе «Система» и здесь не показываются.
 */
import { PEOPLE, PROJECTS } from "./data";
import { directoryByGuid, searchDirectory } from "./demoAuth";
import { settingValue } from "./demoSystem";
import { NOW, minutesAgo, uuidFrom } from "./ids";
import { PERSONAS } from "./personas";

type Role = "admin" | "moderator" | "presale" | "presale_head";
type Status = "active" | "blocked" | "pending_password" | "anonymized";
type DemoUser = {
  id: string;
  login: string;
  full_name: string;
  email: string | null;
  roles: Role[];
  status: Status;
  block_reason: "manual" | "ad_disabled" | null;
  last_login_at: string | null;
  totp_enabled: boolean;
  /** заведён из каталога AD */
  ad: boolean;
};

const user = (
  login: string,
  full_name: string,
  roles: Role[],
  patch: Partial<DemoUser> = {},
): DemoUser => ({
  id: uuidFrom("user", login),
  login,
  full_name,
  email: `${login}@corp.local`,
  roles,
  status: "active",
  block_reason: null,
  last_login_at: minutesAgo(60 * (login.length % 9) + 30),
  totp_enabled: true,
  ad: false,
  ...patch,
});

function seed(): DemoUser[] {
  const P = PERSONAS;
  return [
    user(P.admin.login, P.admin.fullName, ["admin"], { last_login_at: NOW }),
    user(P.expert.login, P.expert.fullName, ["moderator"]),
    user(P.moderator.login, P.moderator.fullName, ["moderator"]),
    user(P.presale.login, P.presale.fullName, ["presale"]),
    user(P.presale_head.login, P.presale_head.fullName, ["presale_head"]),
    user(PEOPLE.kuznetsova.login, PEOPLE.kuznetsova.fullName, [], {
      email: null,
    }),
    user(PEOPLE.morozov.login, PEOPLE.morozov.fullName, []),
    user(PEOPLE.petrov.login, PEOPLE.petrov.fullName, []),
    user(PEOPLE.orlova.login, PEOPLE.orlova.fullName, [], {
      totp_enabled: false,
    }),
    user(PEOPLE.novikov.login, PEOPLE.novikov.fullName, [], {
      status: "blocked",
      block_reason: "manual",
    }),
    user("t.lebedeva", "Т. Лебедева", ["moderator"], {
      status: "pending_password",
      last_login_at: null,
      totp_enabled: false,
    }),
  ];
}

let users = seed();
const replaced: { from: string; to: string; projects: string[] }[] = [];

export function resetDemoUsers() {
  users = seed();
  replaced.length = 0;
}

const adMode = () => settingValue("auth.mode") === "ad";

/** Ответ по схеме User: в режиме AD — источник «ad», роли «Модератор»/«Пресейл» из групп. */
function out(u: DemoUser) {
  const mapping = settingValue("auth.ad.role_mapping") as { enabled: boolean };
  const fromGroups = adMode() && mapping.enabled;
  return {
    id: u.id,
    login: u.login,
    full_name: u.full_name,
    email: u.email,
    source: u.ad || adMode() ? ("ad" as const) : ("local" as const),
    system_roles: u.roles.map((role) => ({
      role,
      source:
        fromGroups && (role === "moderator" || role === "presale")
          ? ("ad_group" as const)
          : ("manual" as const),
    })),
    status: u.status,
    block_reason: u.block_reason,
    last_login_at: u.last_login_at,
    totp_enabled: u.totp_enabled,
  };
}

export function list(q: Record<string, string | undefined>) {
  const needle = (q.q ?? "").trim().toLowerCase();
  const rows = users
    .filter(
      (u) =>
        (!needle ||
          u.login.includes(needle) ||
          u.full_name.toLowerCase().includes(needle)) &&
        (!q.status || u.status === q.status) &&
        (!q.role || u.roles.some((r) => r === q.role)),
    )
    .sort((a, b) => a.full_name.localeCompare(b.full_name, "ru"));
  const offset = Number(q.cursor ?? 0) || 0;
  const limit = Math.min(Math.max(Number(q.limit ?? 50) || 50, 1), 200);
  return {
    items: rows.slice(offset, offset + limit).map(out),
    next_cursor: offset + limit < rows.length ? String(offset + limit) : null,
  };
}

const find = (id: string) => users.find((u) => u.id === id) ?? null;

export function get(id: string) {
  const u = find(id);
  return u ? out(u) : null;
}

export type UserError =
  | "NOT_FOUND"
  | "ALREADY_EXISTS"
  | "AD_USER_NOT_IN_GROUP"
  | "VALIDATION_FAILED"
  | "FORBIDDEN";

const GRANTABLE = new Set<string>(["moderator", "presale", "presale_head"]);

function rolesOf(value: unknown): Role[] | null {
  if (value === undefined) return [];
  if (!Array.isArray(value)) return null;
  const roles = value.filter((r): r is Role => GRANTABLE.has(String(r)));
  return roles.length === value.length ? [...new Set(roles)] : null;
}

function activation(u: DemoUser) {
  return {
    emailed: u.email !== null,
    activation_url:
      u.email === null
        ? `https://estimator.corp.local/activate#${u.id.slice(0, 8)}demo`
        : null,
    expires_at: new Date(Date.parse(NOW) + 72 * 3600_000).toISOString(),
  };
}

export function create(body: unknown) {
  const b = new Map(
    Object.entries(body && typeof body === "object" ? body : {}),
  );
  const roles = rolesOf(b.get("roles"));
  if (!roles) return { error: "VALIDATION_FAILED" as const };
  const guid = b.get("ad_object_guid");
  if (typeof guid === "string") {
    const entry = directoryByGuid(guid);
    if (!entry) return { error: "NOT_FOUND" as const };
    if (!entry.in_access_group)
      return { error: "AD_USER_NOT_IN_GROUP" as const };
    if (users.some((u) => u.login === entry.login))
      return { error: "ALREADY_EXISTS" as const };
    const u = user(entry.login, entry.full_name, roles, {
      email: entry.email,
      ad: true,
      last_login_at: null,
      totp_enabled: false,
    });
    users.push(u);
    return { user: out(u), activation: null };
  }
  const login = String(b.get("login") ?? "").trim();
  const fullName = String(b.get("full_name") ?? "").trim();
  // пустое тело (проверка моков по схеме) — ответ без записи
  if (!login && !fullName) {
    const u = user("new.user", "Новый пользователь", roles, {
      status: "pending_password",
    });
    return { user: out(u), activation: activation(u) };
  }
  if (!/^[A-Za-z0-9._-]{3,64}$/.test(login) || !fullName)
    return { error: "VALIDATION_FAILED" as const };
  if (users.some((u) => u.login === login))
    return { error: "ALREADY_EXISTS" as const };
  const email = b.get("email");
  const u = user(login, fullName, roles, {
    email: typeof email === "string" && email ? email : null,
    status: "pending_password",
    last_login_at: null,
    totp_enabled: false,
  });
  users.push(u);
  return { user: out(u), activation: activation(u) };
}

export function patch(id: string, body: unknown, actorId: string) {
  const u = find(id);
  if (!u) return { error: "NOT_FOUND" as const };
  const b = new Map(
    Object.entries(body && typeof body === "object" ? body : {}),
  );
  if (b.has("roles")) {
    const roles = rolesOf(b.get("roles"));
    if (!roles) return { error: "VALIDATION_FAILED" as const };
    const kept = u.roles.filter((r) => !GRANTABLE.has(r));
    const next = [...kept, ...roles];
    if (id === actorId && JSON.stringify(next) !== JSON.stringify(u.roles))
      return { error: "FORBIDDEN" as const };
    u.roles = next;
  }
  const name = b.get("full_name");
  if (typeof name === "string" && name.trim()) u.full_name = name.trim();
  if (b.has("email")) {
    const email = b.get("email");
    u.email = typeof email === "string" && email ? email : null;
  }
  return out(u);
}

export function setBlocked(id: string, blocked: boolean, actorId: string) {
  const u = find(id);
  if (!u) return { error: "NOT_FOUND" as const };
  if (id === actorId) return { error: "FORBIDDEN" as const };
  u.status = blocked ? "blocked" : "active";
  u.block_reason = blocked ? "manual" : null;
  return out(u);
}

export function resetPassword(id: string) {
  const u = find(id);
  if (!u) return { error: "NOT_FOUND" as const };
  u.status = "pending_password";
  return activation(u);
}

export function resetTotp(id: string) {
  const u = find(id);
  if (!u) return "NOT_FOUND" as const;
  u.totp_enabled = false;
  return null;
}

/** «Найти в AD»: `user_id` — если учётка уже заведена. */
export function adSearch(q: string) {
  return {
    items: searchDirectory(q).map((e) => ({
      object_guid: e.object_guid,
      login: e.login,
      full_name: e.full_name,
      email: e.email,
      department: e.department,
      in_access_group: e.in_access_group,
      user_id: users.find((u) => u.login === e.login)?.id ?? null,
    })),
  };
}

const OPEN_QUESTIONS = new Map([
  ["portal", 2],
  ["fns", 0],
]);

/**
 * «Заменить участника» (FR-ADM-05, Q-29): проекты, где пользователь — участник, с его ролями;
 * роль модератора или пресейла переносится, только если такая системная роль есть у замены.
 */
export function replace(id: string, body: unknown) {
  const u = find(id);
  if (!u) return null;
  const b = new Map(
    Object.entries(body && typeof body === "object" ? body : {}),
  );
  const to = find(String(b.get("replacement_user_id") ?? ""));
  const dryRun = b.get("dry_run") !== false;
  const projects = Object.entries(PROJECTS).flatMap(([key, p]) => {
    const mine = p.members.filter(
      (m) => (m.user as { id: string }).id === u.id && m.status !== "blocked",
    );
    if (mine.length === 0) return [];
    const roles = mine.map((m) => ({
      role: m.role as "moderator" | "expert" | "presale",
      discipline_id: (m.discipline_id as string | null) ?? null,
      is_reviewer: Boolean(m.is_reviewer),
    }));
    const lacks = (role: "moderator" | "presale") =>
      roles.some((r) => r.role === role) && !to?.roles.includes(role);
    const problem = lacks("moderator")
      ? ("replacement_lacks_moderator_role" as const)
      : lacks("presale")
        ? ("replacement_lacks_presale_role" as const)
        : null;
    return [
      {
        project_id: p.id,
        name: p.name,
        roles,
        applicable: problem === null,
        problem,
        open_questions: OPEN_QUESTIONS.get(key) ?? 0,
      },
    ];
  });
  if (dryRun || !to) return { projects, applied: false };
  const chosen = new Set(
    Array.isArray(b.get("project_ids"))
      ? (b.get("project_ids") as string[])
      : [],
  );
  const done = projects.filter((p) => p.applicable && chosen.has(p.project_id));
  replaced.push({
    from: u.id,
    to: to.id,
    projects: done.map((p) => p.project_id),
  });
  return { projects: done, applied: true };
}
