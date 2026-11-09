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
import * as demoAuth from "./demoAuth";
import * as demoDiscussions from "./demoDiscussions";
import * as demoDocuments from "./demoDocuments";
import * as demoExports from "./demoExports";
import * as demoOutcome from "./demoOutcome";
import * as demoPortfolio from "./demoPortfolio";
import * as demoSnapshots from "./demoSnapshots";
import * as demoStatsDetails from "./demoStatsDetails";
import * as demoSystem from "./demoSystem";
import * as demoTree from "./demoTree";
import { NOW, TODAY, minutesAgo, uuidFrom } from "./ids";
import { PERSONAS, accessOf, personaId, type Persona } from "./personas";
import { sample, stripMoney } from "./sample";

export type MockResult = { status: number; body: unknown; binary?: boolean };

/** Ответ демо с ошибкой (Problem) вместо успеха: например, 409 при восстановлении из корзины. */
class MockProblem {
  constructor(readonly result: MockResult) {}
}

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
  /** Тело запроса (JSON) или null. */
  body: unknown;
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

/** Критичное действие без свежего подтверждения (SEC-AUTH-05). */
function stepUpRequired() {
  return new MockProblem(
    problem(403, "STEP_UP_REQUIRED", "Подтвердите действие"),
  );
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
  requestBody: unknown = null,
): MockResult {
  const project = projectOf(op, params);
  const global = accessOf(persona, null);
  // проекты портфеля без демо-данных (FE-050): «Стать модератором» проверяется как в чужом проекте
  const portfolioOnly =
    project === null &&
    op.operationId === "joinAsModerator" &&
    demoPortfolio.isPortfolioOnly(params.id ?? "");
  const scoped = project
    ? accessOf(persona, project.key)
    : portfolioOnly
      ? accessOf(persona, "portfolio")
      : null;
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
    body: requestBody,
  };
  const { status, schema, binary } = successResponse(op);
  if (binary) return { status, body: "mock file", binary: true };
  if (!schema) {
    // ответ без тела (204), но демо может отказать или запомнить действие (удаление документа)
    const done = DEMO[op.operationId]?.(ctx, {} as Schema);
    if (done instanceof MockProblem) return done.result;
    return { status, body: null };
  }
  const custom = DEMO[op.operationId]?.(ctx, schema);
  if (custom instanceof MockProblem) return custom.result;
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
    // статус проекта демо можно подменить в тестах (FE-029: «Сведение»)
    status: (p as { status?: string }).status ?? "estimation",
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
      profile_id: demoProfiles.get(disciplineId(key)) ?? profileId(key),
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

/** Шаг 0,5 ч по ROUND_HALF_UP (BR-CALC-03); в демо достаточно чисел JS. */
function demoHours(value: string): string {
  return String(Math.floor(Number(value.replace(",", ".")) * 2 + 0.5) / 2);
}

/** Профиль ветки, выбранный за сессию демо: дисциплина → профиль. */
const demoProfiles = new Map<string, string>();

/** Цепочка типов профиля по умолчанию из названия («Модуль → Функция»). */
function profileChain(name: string): string[] {
  return name
    .split(" → ")
    .map((n) => (NODE_TYPES.includes(n) ? n : "Работа"))
    .map(typeId);
}

const body = (ctx: Ctx) => (ctx.body ?? {}) as Record<string, unknown>;

/** Справочник контрольных соотношений демо: QA к (Бэкенд + Фронтенд), норма 25–35% (6.6). */
const DEMO_RATIO = {
  id: uuidFrom("ratio", "qa-dev"),
  discipline_a_id: disciplineId("d-qa"),
  disciplines_b: [disciplineId("d-backend"), disciplineId("d-frontend")],
  min_pct: "25",
  max_pct: "35",
  is_active: true,
};

const DEMO: Record<string, Demo> = {
  // правка узла: тот же узел с изменениями и новой версией; данные демо не меняются
  patchNode: (ctx) => {
    const node = ctx.project
      ? demoTree.demoNode(ctx.project, ctx.params.id ?? "")
      : undefined;
    if (!ctx.project || !node) return undefined;
    const changes = new Map(
      Object.entries(
        ((ctx.body ?? {}) as { changes?: Record<string, unknown> }).changes ??
          {},
      ),
    );
    const rounded: string[] = [];
    for (const field of ["o", "r", "p"]) {
      const value = changes.get(field);
      if (typeof value !== "string") continue;
      const normal = demoHours(value);
      if (Number(normal) !== Number(value.replace(",", ".")))
        rounded.push(field);
      changes.set(field, normal);
    }
    const saved = demoTree.saveNode(
      ctx.project,
      node,
      Object.fromEntries(changes),
    );
    const version = demoTree.nextProjectVersion();
    // история листа (FE-028): было → стало по каждому изменённому полю
    demoTree.recordHistory(
      saved.id,
      userRef(ctx.persona),
      Object.fromEntries(
        [...changes].map(([k, v]) => [
          k,
          [new Map(Object.entries(node)).get(k) ?? null, v],
        ]),
      ),
      saved.version,
      version,
    );
    return {
      node: saved,
      project_version: version,
      ancestors: [],
      totals: hoursTotals(ctx.project.totals.total),
      branch_status: null,
      rounded,
    };
  },

  getNodeHistory: (ctx) =>
    ctx.project
      ? demoTree.nodeHistory(ctx.project, ctx.params.id ?? "")
      : undefined,

  // FE-029: «Проверено»; у ревьюера-эксперта — самопроверка (в демо — всегда)
  reviewNode: (ctx) =>
    ctx.project
      ? demoTree.reviewNode(
          ctx.project,
          ctx.params.id ?? "",
          body(ctx).reviewed === true,
          userRef(ctx.persona),
          ctx.persona.projects[ctx.project.key]?.role !== "moderator",
        )
      : undefined,
  putBranchStatus: (ctx) => {
    const p = ctx.project;
    if (!p) return undefined;
    const was =
      (
        p.branchStatuses as {
          phase_id: string;
          discipline_id: string;
          status: string;
        }[]
      ).find(
        (b) =>
          b.phase_id === ctx.params.phase &&
          b.discipline_id === ctx.params.discipline,
      )?.status ?? "not_started";
    return {
      phase_id: ctx.params.phase,
      discipline_id: ctx.params.discipline,
      status: typeof body(ctx).status === "string" ? body(ctx).status : "done",
      was,
    };
  },

  // FE-027: операции со структурой дерева
  createNode: (ctx) =>
    ctx.project ? demoTree.createNode(ctx.project, body(ctx)) : undefined,
  splitNode: (ctx) =>
    ctx.project
      ? demoTree.splitNode(ctx.project, ctx.params.id ?? "")
      : undefined,
  collapseSuggestion: (ctx) =>
    ctx.project
      ? demoTree.collapseSuggestion(ctx.project, ctx.params.id ?? "")
      : undefined,
  collapseNode: (ctx) =>
    ctx.project
      ? demoTree.collapseNode(ctx.project, ctx.params.id ?? "", body(ctx))
      : undefined,
  moveNode: (ctx) =>
    ctx.project
      ? demoTree.moveNode(ctx.project, ctx.params.id ?? "", body(ctx))
      : undefined,
  duplicateNode: (ctx) =>
    ctx.project
      ? demoTree.duplicateNode(ctx.project, ctx.params.id ?? "")
      : undefined,
  deleteNode: (ctx) =>
    ctx.project
      ? demoTree.deleteNode(
          ctx.project,
          ctx.params.id ?? "",
          userRef(ctx.persona),
        )
      : undefined,

  // FE-030: обсуждения под строкой
  listNodeMessages: (ctx) =>
    ctx.project
      ? demoDiscussions.nodeFeed(ctx.project, ctx.params.id ?? "")
      : undefined,
  postNodeMessage: (ctx) =>
    ctx.project
      ? demoDiscussions.postMessage(
          ctx.project,
          ctx.params.id ?? "",
          body(ctx),
          userRef(ctx.persona),
        )
      : undefined,
  // CR-007: обсуждение проекта (node_id = null)
  listProjectMessages: (ctx) =>
    ctx.project ? demoDiscussions.nodeFeed(ctx.project, null) : undefined,
  postProjectMessage: (ctx) =>
    ctx.project
      ? demoDiscussions.postMessage(
          ctx.project,
          null,
          body(ctx),
          userRef(ctx.persona),
        )
      : undefined,
  replyThread: (ctx) =>
    ctx.project
      ? demoDiscussions.replyThread(
          ctx.project,
          ctx.params.id ?? "",
          body(ctx),
          userRef(ctx.persona),
        )
      : undefined,
  editMessage: (ctx) =>
    ctx.project
      ? demoDiscussions.editMessage(ctx.project, ctx.params.id ?? "", {
          body: String(body(ctx).body ?? ""),
        })
      : undefined,
  revokeMessage: (ctx) =>
    ctx.project
      ? demoDiscussions.editMessage(ctx.project, ctx.params.id ?? "", {
          revoked: true,
        })
      : undefined,
  resolveThread: (ctx) =>
    ctx.project
      ? demoDiscussions.setThreadStatus(
          ctx.project,
          ctx.params.id ?? "",
          true,
          userRef(ctx.persona),
        )
      : undefined,
  reopenThread: (ctx) =>
    ctx.project
      ? demoDiscussions.setThreadStatus(
          ctx.project,
          ctx.params.id ?? "",
          false,
          userRef(ctx.persona),
        )
      : undefined,
  suggestAddressees: (ctx) =>
    ctx.project
      ? {
          items: demoDiscussions.suggest(
            ctx.project,
            String(ctx.params.q ?? ""),
          ),
        }
      : undefined,

  // FE-031: закрытые заметки (права и TOTP проверяет цепочка прав выше)
  listNotes: (ctx) =>
    ctx.project
      ? demoDiscussions.listNotes(ctx.project, ctx.params.node_id ?? null)
      : undefined,
  createNote: (ctx) =>
    ctx.project
      ? demoDiscussions.createNote(ctx.project, body(ctx), userRef(ctx.persona))
      : undefined,
  patchNote: (ctx) =>
    ctx.project
      ? demoDiscussions.patchNote(ctx.project, ctx.params.id ?? "", body(ctx))
      : undefined,

  // FE-018: корзина. Модератор видит всё, эксперт — свою дисциплину, документы — модератор и
  // пресейл (FR-TREE-24, GAP-06)
  getTrash: (ctx) => {
    const p = ctx.project;
    if (!p) return undefined;
    const member = ctx.persona.projects[p.key];
    const role = member?.role;
    const own = member?.discipline ? disciplineId(member.discipline) : null;
    return {
      items: demoTree.trashOf(p, (kind, discipline) =>
        kind === "document"
          ? role === "moderator" || role === "presale"
          : role === "moderator" || (own !== null && discipline === own),
      ),
    };
  },
  restoreTrash: (ctx) => {
    if (!ctx.project) return undefined;
    const target = body(ctx).target_parent_id;
    const result = demoTree.restoreTrash(
      ctx.project,
      ctx.params.batch_id ?? "",
      typeof target === "string" ? target : null,
    );
    if (result && "unavailable" in result) {
      const err = problem(
        409,
        "RESTORE_TARGET_UNAVAILABLE",
        "Прежнее место недоступно",
      );
      return new MockProblem({
        status: 409,
        body: { ...(err.body as object), reason: result.unavailable },
      });
    }
    return result;
  },
  getOutcome: (ctx) =>
    ctx.project ? demoOutcome.outcomeOf(ctx.project) : undefined,
  putOutcome: (ctx) => {
    if (!ctx.project) return undefined;
    const result = demoOutcome.putOutcome(
      ctx.project,
      ctx.body,
      ctx.permissions.has("money.write"),
    );
    if ("error" in result) {
      const err =
        result.error === "FORBIDDEN"
          ? problem(403, "FORBIDDEN", "Недостаточно прав")
          : problem(422, "VALIDATION_FAILED", "Ошибка в данных");
      return new MockProblem({
        status: err.status,
        body: {
          ...(err.body as object),
          ...(result.error === "VALIDATION_FAILED"
            ? {
                errors: [
                  {
                    field: `/${result.field}`,
                    code: "required",
                    message: "Обязательное поле",
                  },
                ],
              }
            : {}),
        },
      });
    }
    return result;
  },
  listLossReasons: (ctx, schema) =>
    list(
      schema,
      demoOutcome.lossReasons(ctx.params.include_inactive === "true"),
    ),
  // FE-060 · раздел «Система» (FR-SA-07, BR-ROLE-03, FR-SA-04)
  getHealth: () => demoSystem.health(),
  listAdmins: (_ctx, schema) => list(schema, demoSystem.admins()),
  getSettings: (ctx) => demoSystem.settings(ctx.params.section ?? ""),
  // FE-061 · способ входа и AD (11.2 №2–6); критичные записи — со step-up (SEC-AUTH-05)
  stepUp: () => demoSystem.stepUp(),
  putSettings: (ctx) => {
    if (!demoSystem.stepUpFresh()) return stepUpRequired();
    const section = ctx.params.section ?? "";
    const values = new Map(Object.entries(body(ctx))).get("values") ?? {};
    if (section === "auth") {
      const missing = demoAuth.missingChecks(values);
      if (missing.length) {
        const err = problem(
          409,
          "AD_CHECKS_REQUIRED",
          "Сначала проверьте подключение и вход",
        );
        return new MockProblem({
          status: 409,
          body: { ...(err.body as object), missing },
        });
      }
    }
    const result = demoSystem.saveSettings(section, values);
    if (section === "auth") demoAuth.afterSave();
    return result;
  },
  adTestConnection: (ctx) => demoAuth.testConnection(ctx.body),
  adTestLogin: (ctx) => demoAuth.testLogin(ctx.body),
  switchMode: (ctx) => {
    const dryRun = new Map(Object.entries(body(ctx))).get("dry_run") !== false;
    if (!dryRun && !demoSystem.stepUpFresh()) return stepUpRequired();
    const out = demoAuth.switchMode(ctx.body);
    if ("report" in out) return out.report;
    const err =
      out.error === "MODE_SWITCH_NOT_ALLOWED"
        ? problem(409, out.error, "Переход недоступен в интерфейсе")
        : problem(409, out.error, "Есть нерешённые совпадения");
    return new MockProblem({
      status: 409,
      body: {
        ...(err.body as object),
        ...("unresolved" in out ? { unresolved: out.unresolved } : {}),
      },
    });
  },
  switchModeResolve: (ctx) => {
    if (!demoSystem.stepUpFresh()) return stepUpRequired();
    return demoAuth.resolve(ctx.body);
  },
  // FE-050 · портфель руководителя пресейла (FR-PORT-01…03)
  portfolioProjects: (ctx, schema) =>
    list(schema, demoPortfolio.portfolioProjects(ctx.params)),
  portfolioSummary: (ctx) => demoPortfolio.portfolioSummary(ctx.params),
  portfolioExport: (ctx) => {
    const b = body(ctx);
    const from = typeof b.from === "string" ? b.from : TODAY;
    const to = typeof b.to === "string" ? b.to : TODAY;
    return demoExports.createExport(
      "portfolio_xlsx",
      `Портфель_${from}_${to}.xlsx`,
    );
  },
  exportStatsTab: (ctx) =>
    demoExports.createExport(
      "stats_tab_xlsx",
      `Статистика_${ctx.params.tab ?? "tab"}.xlsx`,
    ),
  exportAssumptions: () =>
    demoExports.createExport("assumptions_docx", "Допущения_и_риски.docx"),
  // FE-043: вопросы заказчику и обсуждения проекта
  listCustomerQuestions: (ctx) =>
    ctx.project
      ? demoDiscussions.customerQuestions(ctx.project, ctx.params)
      : undefined,
  listThreads: (ctx) =>
    ctx.project
      ? demoDiscussions.projectThreads(
          ctx.project,
          ctx.params,
          userRef(ctx.persona).id,
        )
      : undefined,
  exportCustomerQuestions: (ctx) => {
    const req = body(ctx);
    const ids = Array.isArray(req.thread_ids)
      ? (req.thread_ids as string[])
      : [];
    if (ctx.project) demoDiscussions.markSent(ctx.project, ids);
    return req.format === "xlsx"
      ? demoExports.createExport("cq_xlsx", "Вопросы_заказчику.xlsx")
      : demoExports.createExport("cq_docx", "Вопросы_заказчику.docx");
  },
  answerCustomerQuestion: (ctx) =>
    ctx.project
      ? demoDiscussions.answerQuestion(
          ctx.project,
          ctx.params.id ?? "",
          String(body(ctx).body ?? ""),
          userRef(ctx.persona),
        )
      : undefined,
  withdrawCustomerQuestion: (ctx) =>
    ctx.project
      ? demoDiscussions.withdrawQuestion(
          ctx.project,
          ctx.params.id ?? "",
          String(body(ctx).reason ?? ""),
        )
      : undefined,
  getExport: (ctx) => demoExports.exportJob(ctx.params.id ?? "") ?? undefined,
  joinAsModerator: (ctx, schema) => {
    const result = demoPortfolio.joinAsModerator(
      ctx.params.id ?? "",
      ctx.persona,
    );
    if ("error" in result)
      return new MockProblem(
        result.error === "NOT_FOUND"
          ? problem(404, "NOT_FOUND", "Не найдено")
          : problem(
              409,
              "PROJECT_STATUS_CONFLICT",
              "Сначала восстановите проект",
            ),
      );
    return list(
      schema,
      result.map((user) => ({
        user,
        role: "moderator",
        discipline_id: null,
        is_reviewer: false,
        status: "active",
        added_by_admin_self: false,
      })),
    );
  },
  listDocuments: (ctx) =>
    ctx.project ? demoDocuments.listDocuments(ctx.project) : undefined,
  uploadDocument: (ctx) => {
    if (!ctx.project) return undefined;
    const result = demoDocuments.uploadDocument(
      ctx.project,
      ctx.body,
      userRef(ctx.persona),
    );
    if (!("error" in result)) return result;
    const status = new Map([
      ["VALIDATION_FAILED", 422],
      ["UNSUPPORTED_MEDIA_TYPE", 415],
      ["PAYLOAD_TOO_LARGE", 413],
      ["PROJECT_STORAGE_LIMIT", 409],
    ]).get(result.error);
    return new MockProblem(problem(status ?? 422, result.error, result.error));
  },
  deleteDocument: (ctx) =>
    ctx.project &&
    !demoDocuments.deleteDocument(
      ctx.project,
      ctx.params.id ?? "",
      userRef(ctx.persona),
    )
      ? new MockProblem(problem(404, "NOT_FOUND", "Не найдено"))
      : undefined,
  restoreDocument: (ctx) =>
    ctx.project
      ? demoTree.restoreDocument(ctx.project, ctx.params.id ?? "")
      : undefined,
  copyBranchFrom: (ctx) =>
    ctx.project
      ? demoTree.copyBranchFrom(ctx.project, ctx.params.id ?? "", body(ctx))
      : undefined,
  // тип сразу работает в проекте: попадает в listProjectNodeTypes до перезагрузки
  createLocalNodeType: (ctx) =>
    ctx.project
      ? demoTree.addLocalType({
          id: uuidFrom("node-type", "local", String(body(ctx).name)),
          name: String(body(ctx).name),
          icon: String(body(ctx).icon),
          norms: [],
          is_system: false,
          is_active: true,
          project_id: ctx.project.id,
        })
      : undefined,
  patchDisciplineProfile: (ctx) => {
    const d = DISCIPLINES.find(
      (x) => disciplineId(x.key) === ctx.params.discipline_id,
    );
    if (!d) return undefined;
    const profile = String(body(ctx).profile_id);
    // профиль только из профилей этой дисциплины
    if ([profileId(d.key), profileId(`${d.key}-alt`)].includes(profile))
      demoProfiles.set(disciplineId(d.key), profile);
    return {
      discipline_id: disciplineId(d.key),
      name: d.name,
      profile_id: demoProfiles.get(disciplineId(d.key)) ?? profileId(d.key),
      has_expert: true,
    };
  },
  listProfiles: (_ctx, schema) =>
    list(
      schema,
      DISCIPLINES.flatMap((d) => [
        {
          id: profileId(d.key),
          discipline_id: disciplineId(d.key),
          name: d.profile,
          type_chain: profileChain(d.profile),
          is_active: true,
        },
        {
          id: profileId(`${d.key}-alt`),
          discipline_id: disciplineId(d.key),
          name: "Модуль → Работа",
          type_chain: profileChain("Модуль → Работа"),
          is_active: true,
        },
      ]),
    ),

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

  listSnapshots: (ctx, schema) =>
    ctx.project
      ? list(schema, demoSnapshots.snapshotsOf(ctx.project))
      : undefined,

  // FE-045: снимок, «ошибочный» и экспорт проекта (FR-SNAP-01/02, FR-EXP-01…05)
  createSnapshot: (ctx) =>
    ctx.project
      ? demoSnapshots.createSnapshot(
          ctx.project,
          body(ctx),
          userRef(ctx.persona),
        )
      : undefined,
  invalidateSnapshot: (ctx) =>
    ctx.project
      ? demoSnapshots.invalidateSnapshot(ctx.project, ctx.params.id ?? "")
      : undefined,
  createExport: (ctx) => {
    const req = body(ctx);
    const money = req.kind === "money_xlsx";
    const snap = typeof req.snapshot_id === "string" ? req.snapshot_id : null;
    const name = `${ctx.project?.name ?? "Проект"}_${snap ? "снимок" : TODAY}_${money ? "деньги" : "часы"}.xlsx`;
    return demoExports.createExport(
      money ? "money_xlsx" : "hours_xlsx",
      name.replace(/[\\/:*?"<>|]/g, "_"),
      4000,
    );
  },
  diffSnapshot: (ctx) =>
    ctx.project
      ? demoSnapshots.diffOf(
          ctx.project,
          ctx.params.id ?? "",
          ctx.params.with ?? "current",
          ctx.money,
        )
      : undefined,
  exportDiff: () =>
    demoExports.createExport("snapshot_diff_xlsx", "Сравнение.xlsx"),

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
      // контрольное соотношение QA к (Бэкенд + Фронтенд), норма 25–35% (6.6, `stats.png` №9)
      ratios: (() => {
        const e = (key: string) =>
          new Decimal(
            new Map(Object.entries(t.byDiscipline)).get(key)?.e ?? "0",
          );
        const base = e("d-backend").plus(e("d-frontend"));
        const pct = base.isZero()
          ? null
          : e("d-qa").div(base).times(100).toFixed(1);
        const n = pct === null ? null : Number(pct);
        return [
          {
            ratio_id: DEMO_RATIO.id,
            pct,
            min_pct: "25",
            max_pct: "35",
            verdict:
              n === null ? null : n < 25 ? "below" : n > 35 ? "above" : "ok",
          },
        ];
      })(),
      // «Проверено ревьюерами» как на `stats.png` №10
      reviewed:
        p.key === "portal"
          ? [
              {
                discipline_id: disciplineId("d-backend"),
                reviewed_pct: "13.7",
                self_review_pct: "100",
              },
              {
                discipline_id: disciplineId("d-frontend"),
                reviewed_pct: "100",
                self_review_pct: "0",
              },
              {
                discipline_id: disciplineId("d-qa"),
                reviewed_pct: "0",
                self_review_pct: null,
              },
            ]
          : [],
      // FE-042 · объёмы и кандидаты — по дереву, метки — строки макета
      volumes: demoStatsDetails.volumes(
        p,
        (id) => NODE_TYPES.find((name) => typeId(name) === id) ?? "Работа",
      ),
      candidates: demoStatsDetails.candidates(p),
      tag_lists: demoStatsDetails.tagLists(p),
      // FE-041 · точка в день (GAP-01) за 8 дней, последняя — текущий итог
      dynamics: demoSnapshots.dynamicsOf(p),
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
              // E дисциплины × ставка по всем фазам; ставки нет — null («—», 11.8 №6)
              cost_by_discipline: Object.entries(t.byDiscipline).map(
                ([key, row]) => {
                  const rate = new Map(Object.entries(p.money.rates)).get(key);
                  return {
                    discipline_id: disciplineId(key),
                    cost_rub: rate
                      ? new Decimal(row.e).times(rate).toFixed(0)
                      : null,
                  };
                },
              ),
              // стоимость работ фазы — по её доле в часах работ, итог «Работы» — сумма строк
              cost_by_phase: (() => {
                const rates = new Map(Object.entries(p.money.rates));
                const worksCost = Object.entries(t.byDiscipline).reduce(
                  (acc, [key, row]) =>
                    acc.plus(new Decimal(row.e).times(rates.get(key) ?? 0)),
                  new Decimal(0),
                );
                return Object.entries(t.byPhase).map(([key, row]) => ({
                  phase_id: phaseId(key),
                  cost_rub: works.isZero()
                    ? null
                    : worksCost.times(row.e).div(works).toFixed(0),
                }));
              })(),
              dynamics: demoSnapshots.moneyDynamicsOf(p),
              snapshots: demoSnapshots.snapshotsOf(p).map((snap) => ({
                snapshot_id: snap.id,
                quote_cur: snap.money.quote_cur,
              })),
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

  listRatios: (_ctx, schema) => list(schema, [DEMO_RATIO]),
  getMethodSettings: () => demoSystem.methodSettings(),
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

  listNodeTypes: (_ctx, schema) => list(schema, dictionaryNodeTypes()),

  // CR-006: типы словаря и локальные типы проекта (в «Портале дилеров» — «Шлюз оплаты»)
  listProjectNodeTypes: (ctx, schema) =>
    ctx.project
      ? list(schema, [
          ...dictionaryNodeTypes(),
          ...(ctx.project.key === "portal"
            ? [
                {
                  id: typeId("local:Шлюз оплаты"),
                  name: "Шлюз оплаты",
                  icon: "credit_card",
                  norms: [],
                  is_system: false,
                  is_active: true,
                  project_id: ctx.project.id,
                },
              ]
            : []),
          ...demoTree.localTypesOf(ctx.project),
        ])
      : undefined,
};

function dictionaryNodeTypes() {
  return NODE_TYPES.map((name) => ({
    id: typeId(name),
    name,
    icon: NODE_TYPE_ICONS.get(name) ?? "work",
    norms: [],
    is_system: name === "Работа",
    is_active: true,
    project_id: null,
  }));
}
