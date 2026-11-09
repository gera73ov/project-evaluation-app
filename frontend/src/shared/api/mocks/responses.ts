/**
 * FE-001 · ответ мока на операцию OpenAPI: проверка прав по роли переключателя, затем
 * демо-данные (для главных экранов) или пример по схеме контракта (для остальных).
 *
 * Цепочка прав как у сервера (permissions.yaml, R-OBJECT-CHAIN): нет доступа к проекту →
 * 404 NOT_FOUND; доступ есть, права нет → 403 FORBIDDEN. Без `money.read` денежных ключей в
 * ответе нет (SEC-AUTHZ-04). Изменяющие запросы ничего не сохраняют: ответ — пример по схеме.
 */
import Decimal from "decimal.js";

import {
  PSEUDO_PERMISSIONS,
  successResponse,
  type Operation,
  type Schema,
} from "./contract";
import {
  DISCIPLINES,
  NODE_TYPES,
  PHASES,
  PEOPLE,
  PROJECTS,
  disciplineId,
  hours,
  hoursTotals,
  phaseId,
  profileId,
  projectKeyOf,
  typeId,
  userRef,
  type DemoProject,
} from "./data";
import { NOW, TODAY, minutesAgo, uuidFrom } from "./ids";
import { PERSONAS, accessOf, personaId, type Persona } from "./personas";
import { sample, stripMoney } from "./sample";

export type MockResult = { status: number; body: unknown; binary?: boolean };

/** Пути, объекты которых принадлежат проекту (права — по членству в нём). */
const PROJECT_SCOPED =
  /^\/(projects\/\{id\}|nodes|threads|messages|notes|documents|snapshots|trash|exports|me\/view-state)(\/|$)/;

/** Операции, где деньги решаются по каждому проекту в ответе, а не по проекту запроса. */
const PER_PROJECT_MONEY = new Set(["listProjects"]);

type Ctx = {
  persona: Persona;
  project: DemoProject | null;
  permissions: Set<string>;
  money: boolean;
  params: Record<string, string>;
};

function problem(status: number, code: string, title: string): MockResult {
  return {
    status,
    body: {
      type: `https://estimator.local/errors/${code}`,
      title,
      status,
      code,
      error_id: uuidFrom("error", code),
    },
  };
}

function projectOf(
  op: Operation,
  params: Record<string, string>,
): DemoProject | null | undefined {
  if (!PROJECT_SCOPED.test(op.path)) return undefined; // операция вне проекта
  const id = params.id ?? params.project_id ?? params.batch_id;
  const key = projectKeyOf(id);
  if (key) return PROJECTS[key];
  // /projects/{id} с неизвестным id — чужой или несуществующий проект; узлы, треды и прочие
  // объекты без демо-данных считаются объектами «Портала дилеров»
  return op.path.startsWith("/projects/") ||
    op.path.startsWith("/me/view-state")
    ? null
    : PROJECTS.portal;
}

/** Ответ мока на операцию от имени персоны. */
export function mockResponse(
  op: Operation,
  params: Record<string, string>,
  persona: Persona,
): MockResult {
  const project = projectOf(op, params);
  const global = accessOf(persona, null);
  const scoped = project ? accessOf(persona, project.key) : null;
  const permissions = new Set([
    ...global.permissions,
    ...(scoped?.permissions ?? []),
  ]);
  const pseudo = op.permission.some((p) => PSEUDO_PERMISSIONS.has(p));
  const granted = pseudo || op.permission.some((p) => permissions.has(p));

  if (
    project !== undefined &&
    !scoped?.access &&
    !op.permission.some((p) => global.permissions.has(p)) &&
    !pseudo
  ) {
    return problem(404, "NOT_FOUND", "Не найдено");
  }
  if (!granted) return problem(403, "FORBIDDEN", "Недостаточно прав");

  // деньги: право money.read в проекте или портфель руководителя пресейла (FR-PORT-01)
  const money =
    permissions.has("money.read") || permissions.has("portfolio.read");
  const ctx: Ctx = {
    persona,
    project: project ?? null,
    permissions,
    money,
    params,
  };
  const { status, schema, binary } = successResponse(op);
  if (binary) return { status, body: "mock file", binary: true };
  if (!schema) return { status, body: null };
  const custom = DEMO[op.operationId]?.(ctx, schema);
  const body =
    custom === undefined
      ? sample(schema, { money: ctx.money }, op.operationId)
      : custom;
  // список «Мои оценки» сам решает по каждому проекту, показывать ли деньги (FR-HOME-04)
  if (custom !== undefined && PER_PROJECT_MONEY.has(op.operationId))
    return { status, body };
  return { status, body: stripMoney(schema, body, { money: ctx.money }) };
}

/** Пример по схеме, поверх которого лежат демо-поля. */
function overlay(
  schema: Schema,
  ctx: Ctx,
  fields: Record<string, unknown>,
): Record<string, unknown> {
  return {
    ...(sample(schema, { money: ctx.money }) as Record<string, unknown>),
    ...fields,
  };
}

/** Обёртка списка по схеме ответа: `next_cursor` — только если он есть в контракте. */
const list = (schema: Schema, items: unknown[]) =>
  schema.properties && "next_cursor" in schema.properties
    ? { items, next_cursor: null }
    : { items };

// --- демо-ответы главных экранов ----------------------------------------------------------

type Demo = (ctx: Ctx, schema: Schema) => unknown;

function myRoles(ctx: Ctx, p: DemoProject) {
  const m = ctx.persona.projects[p.key];
  if (!m) return [];
  return [
    {
      role: m.role,
      discipline_id: m.discipline ? disciplineId(m.discipline) : null,
      is_reviewer: m.isReviewer,
    },
  ];
}

function projectBody(ctx: Ctx, p: DemoProject, schema: Schema) {
  const access = accessOf(ctx.persona, p.key);
  return overlay(schema, ctx, {
    id: p.id,
    name: p.name,
    customer: p.customer,
    description: p.description,
    status: "estimation",
    outcome: "unknown",
    detail_level: "medium",
    pm_percent: p.key === "portal" ? "18" : "15",
    pm_percent_reason: "",
    quote_figure: "p80",
    duration_weeks: p.key === "portal" ? 12 : 6,
    deadline: p.deadline,
    version: 21,
    phases: p.phases.map((key) => {
      const ph = PHASES.find((x) => x.key === key);
      return {
        phase_id: phaseId(key),
        name: ph?.name ?? key,
        is_cross_cutting: Boolean(ph?.cross),
        is_enabled: true,
        in_pm_base: !ph?.cross,
      };
    }),
    disciplines: p.disciplines.map((key) => ({
      discipline_id: disciplineId(key),
      name: DISCIPLINES.find((d) => d.key === key)?.name ?? key,
      profile_id: profileId(key),
      has_expert: p.members.some(
        (m) =>
          (m as { discipline_id: string | null }).discipline_id ===
          disciplineId(key),
      ),
    })),
    completed_at: null,
    archived_at: null,
    cancel_reason: null,
    created_at: minutesAgo(60 * 24 * 14),
    access: access.access === "presale_head" ? "presale_head" : "member",
    my_permissions: [...access.permissions].sort(),
    support_expires_at: null,
  });
}

function moneyFigure(p: DemoProject, figure: "e" | "p80" | "p90") {
  const f = p.money.figures[figure];
  const rows = (src: Record<string, string>) =>
    Object.entries(src).map(([d, amount]) => ({
      discipline_id: d === "pm" ? null : disciplineId(d),
      amount,
    }));
  return {
    k: f.k,
    rows_rub: rows(f.rows_rub),
    total_rub: f.total_rub,
    vat_rub: f.vat_rub,
    total_with_vat_rub: f.total_with_vat_rub,
    rows_cur: rows(f.rows_cur),
    total_cur: f.total_cur,
    vat_cur: f.vat_cur,
    total_with_vat_cur: f.total_with_vat_cur,
  };
}

/** Ключи иконок типов по умолчанию (DESIGN.md 16.3). */
const NODE_TYPE_ICONS = new Map([
  ["Модуль", "module"],
  ["Функция", "function"],
  ["Экран", "screen"],
  ["Интеграция", "integration"],
  ["Отчёт", "report"],
  ["Сущность", "entity"],
  ["Сервис", "service"],
  ["Тест-набор", "test_suite"],
  ["Документ", "document"],
  ["Работа", "work"],
]);

const DEMO: Record<string, Demo> = {
  getMe: (ctx) => ({
    id: personaId(ctx.persona),
    login: ctx.persona.login,
    full_name: ctx.persona.fullName,
    email: `${ctx.persona.login}@example.test`,
    source: "local",
    timezone: "Europe/Moscow",
    system_roles: ctx.persona.systemRoles,
    totp_enabled: true,
    totp_required:
      ctx.persona.systemRoles.some(
        (r) => r !== "moderator" && r !== "presale",
      ) || ctx.persona.key === "moderator",
    mfa_passed: true,
    auth_mode: "app",
    session_expires_at: new Date(Date.parse(NOW) + 8 * 3600_000)
      .toISOString()
      .replace(".000Z", "Z"),
    idle_timeout_seconds: 1800,
  }),

  listProjects: (ctx, schema) =>
    list(
      schema,
      Object.values(PROJECTS)
        .filter((p) => ctx.persona.projects[p.key])
        .map((p) => {
          const money = accessOf(ctx.persona, p.key).permissions.has(
            "money.read",
          );
          const quote = p.money.figures.p80;
          return {
            id: p.id,
            name: p.name,
            customer: p.customer,
            status: "estimation",
            my_roles: myRoles(ctx, p),
            my_progress:
              p.key === "portal"
                ? { done: 2, total: 3 }
                : { done: 0, total: 6 },
            deadline: p.deadline,
            deadline_alert: p.key === "portal",
            questions_to_me: p.key === "portal" ? 2 : 1,
            updated_at:
              p.key === "portal" ? minutesAgo(10) : minutesAgo(60 * 20),
            quote_figure: "p80",
            quote_hours: hours(p.totals.total.p80 ?? p.totals.total.e),
            ...(money
              ? {
                  money: {
                    currency: p.money.currency,
                    quote_cur: quote.total_cur,
                    quote_rub: quote.total_rub,
                    rates_missing: false,
                  },
                }
              : {}),
          };
        }),
    ),

  getProject: (ctx, schema) =>
    ctx.project ? projectBody(ctx, ctx.project, schema) : undefined,

  getMembers: (ctx, schema) =>
    ctx.project ? list(schema, ctx.project.members) : undefined,

  // CR-005: кандидаты в команду — активные, без суперадминистратора и аудитора ИБ
  getMemberCandidates: (ctx, schema) =>
    ctx.project
      ? list(schema, [
          ...Object.values(PERSONAS)
            .filter(
              (p) =>
                !p.systemRoles.some(
                  (r) => r === "superadmin" || r === "security_auditor",
                ),
            )
            .map((p) => ({
              user: userRef(p),
              system_roles: [...p.systemRoles],
            })),
          ...Object.values(PEOPLE).map((p) => ({
            user: userRef(p),
            system_roles: [],
          })),
        ])
      : undefined,

  getTree: (ctx) => {
    const p = ctx.project;
    if (!p) return undefined;
    return {
      project_version: 21,
      nodes: p.nodes,
      branch_statuses: p.branchStatuses,
      totals: {
        works: hoursTotals(p.totals.works),
        pm: hoursTotals(p.totals.pm),
        total: hoursTotals(p.totals.total),
        unaccounted_leaves: 0,
        nodes_count: p.nodes.length,
        nodes_limit: 5000,
      },
    };
  },

  getMoney: (ctx) => {
    const p = ctx.project;
    if (!p) return undefined;
    return {
      currency: p.money.currency,
      exchange_rate: p.money.exchangeRate,
      vat_rate_id: uuidFrom("vat", p.money.vatPercent),
      vat_percent: p.money.vatPercent,
      rates: Object.entries(p.money.rates).map(([d, rate]) => ({
        discipline_id: d === "pm" ? null : disciplineId(d),
        rate_rub: rate,
      })),
      rates_missing: [],
      figures: {
        e: moneyFigure(p, "e"),
        p80: moneyFigure(p, "p80"),
        p90: moneyFigure(p, "p90"),
      },
      updated_at: minutesAgo(60 * 24),
      project_version: 21,
    };
  },

  getStats: (ctx, schema) => {
    const p = ctx.project;
    if (!p) return undefined;
    const t = p.totals;
    const works = new Decimal(t.works.e);
    const share = (e: string) =>
      works.isZero() ? null : new Decimal(e).div(works).times(100).toFixed(1);
    return overlay(schema, ctx, {
      project_version: 21,
      readiness: p.branchStatuses.map((b) => {
        const disc =
          DISCIPLINES.find((d) => disciplineId(d.key) === b.discipline_id)
            ?.key ?? "";
        return {
          phase_id: b.phase_id,
          discipline_id: b.discipline_id,
          e: hours(
            (p.nodes.find(
              (n) =>
                n.kind === "discipline" &&
                n.phase_id === b.phase_id &&
                n.discipline_id === b.discipline_id,
            )?.e as string) ?? "0",
          ),
          status: b.status,
          last_change_at: b.changed_at,
          flags:
            (b.open_questions as number) > 0
              ? ["open_question"]
              : disc === "d-analytics"
                ? ["large"]
                : [],
          overdue_working_days: null,
        };
      }),
      totals: {
        by_phase: Object.entries(t.byPhase).map(([key, row]) => ({
          phase_id: phaseId(key),
          hours: hoursTotals(row),
          share_pct: share(row.e),
        })),
        by_discipline: Object.entries(t.byDiscipline).map(([key, row]) => ({
          discipline_id: disciplineId(key),
          hours: hoursTotals(row),
          share_pct: share(row.e),
        })),
        works: hoursTotals(t.works),
        pm: hoursTotals(t.pm),
        total: hoursTotals(t.total),
        quote_figure: "p80",
        duration_weeks: p.key === "portal" ? 12 : 6,
      },
      dynamics: [
        {
          date: TODAY,
          e: hours(t.total.e),
          p80: hours(t.total.p80 ?? t.total.e),
        },
      ],
      ...(ctx.money
        ? {
            money: {
              ...(sample((schema.properties?.money ?? {}) as Schema, {
                money: true,
              }) as object),
              figures: {
                e: moneyFigure(p, "e"),
                p80: moneyFigure(p, "p80"),
                p90: moneyFigure(p, "p90"),
              },
            },
          }
        : {}),
    });
  },

  getJournal: (ctx) => {
    const p = ctx.project;
    if (!p) return undefined;
    const by = userRef(PERSONAS.moderator);
    const entry = (
      n: number,
      minutes: number,
      action: string,
      changes: object,
      extra: object = {},
    ) => ({
      id: uuidFrom("journal", p.key, String(n)),
      created_at: minutesAgo(minutes),
      user: by,
      action,
      changes,
      ...extra,
    });
    // денежная запись приходит только с money.read (CORE-032, 15.2)
    const items = [
      entry(1, 35, "project.settings", {
        pm_percent: ["15", "18"],
        deadline: [null, p.deadline],
      }),
      ...(ctx.money
        ? [
            entry(
              2,
              90,
              "money.changed",
              {},
              { money: { changes: { rate_rub: ["2800", "3000"] } } },
            ),
          ]
        : []),
      entry(3, 60 * 26, "team.changed", {
        experts: [[], [PEOPLE.orlova.fullName]],
      }),
      entry(4, 60 * 24 * 3, "project.status", {
        status: ["preparation", "estimation"],
      }),
      entry(5, 60 * 24 * 14, "project.created", {}),
    ];
    return { items, next_cursor: null };
  },

  listNotifications: (ctx) => {
    const portal = PROJECTS.portal;
    const items = ctx.persona.projects.portal
      ? [
          { kind: "question_to_me", node: "n-regress", minutes: 10 },
          { kind: "answer_to_my_question", node: "n-1c", minutes: 25 },
          { kind: "moderator_change", node: "n-profile", minutes: 1 },
        ].map((n) => ({
          id: uuidFrom("notification", ctx.persona.login, n.kind),
          kind: n.kind,
          project_id: portal.id,
          node_id: uuidFrom("node", "portal", n.node),
          payload: {},
          created_at: minutesAgo(n.minutes),
          read_at: null,
        }))
      : [];
    return { items, unread: items.length, next_cursor: null };
  },

  listPhases: (_ctx, schema) =>
    list(
      schema,
      PHASES.map((p, i) => ({
        id: phaseId(p.key),
        name: p.name,
        sort_order: i + 1,
        is_cross_cutting: p.cross,
        is_active: true,
      })),
    ),

  listDisciplines: (_ctx, schema) =>
    list(
      schema,
      DISCIPLINES.map((d) => ({
        id: disciplineId(d.key),
        name: d.name,
        short_name: d.short,
        color: d.color,
        default_profile_id: profileId(d.key),
        is_active: true,
      })),
    ),

  listNodeTypes: (_ctx, schema) =>
    list(
      schema,
      NODE_TYPES.map((name) => ({
        id: typeId(name),
        name,
        icon: NODE_TYPE_ICONS.get(name) ?? "work",
        norms: [],
        is_system: name === "Работа",
        is_active: true,
      })),
    ),
};
