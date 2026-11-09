/**
 * FE-050 · портфель руководителя пресейла в демо (FR-PORT-01…03, 11.13): реестр проектов с
 * деньгами, сводка за период по тем же проектам и «Стать модератором». Два проекта — настоящие
 * демо-проекты (их итог берётся из «Результата пресейла»), остальные — строки макета
 * `portfolio.png` и несколько проектов для показателей. Цифры условные, кроме «Портала дилеров».
 */
import { PERSONAS, type Persona } from "./personas";
import { PEOPLE, PROJECTS, hours, personaId, userRef } from "./data";
import { LOSS_REASONS, outcomeOf } from "./demoOutcome";
import { NOW, minutesAgo, uuidFrom } from "./ids";

type Status =
  | "preparation"
  | "estimation"
  | "consolidation"
  | "completed"
  | "archived";
type Outcome = "unknown" | "won" | "lost" | "cancelled";
type Ref = ReturnType<typeof userRef>;

type Row = {
  id: string;
  name: string;
  customer: string;
  moderators: Ref[];
  presales: Ref[];
  status: Status;
  outcome: Outcome;
  lossReason: string | null;
  lossText: string | null;
  figure: "e" | "p80" | "p90";
  hours: string | null;
  currency: string;
  quoteCur: string | null;
  quoteRub: string | null;
  contract: string | null;
  createdDaysAgo: number;
  updatedDaysAgo: number;
  firstSnapshotDays: number | null;
};

const belova = { login: "t.belova", fullName: "Т. Белова", initials: "ТБ" };
const smirnova = userRef(PERSONAS.moderator);
const sidorov = userRef(PERSONAS.presale);
const ivanov = userRef(PERSONAS.expert);
const morozov = userRef(PEOPLE.morozov);
const orlova = userRef(PEOPLE.orlova);
const reason = (key: string) => uuidFrom("loss-reason", key);

/** Строка без денег — частный случай: ставки не заданы. */
function row(
  key: string,
  fields: Omit<Row, "id" | "lossReason" | "lossText" | "firstSnapshotDays"> &
    Partial<Pick<Row, "lossReason" | "lossText" | "firstSnapshotDays">>,
): Row {
  return {
    id: uuidFrom("project", "portfolio", key),
    lossReason: null,
    lossText: null,
    firstSnapshotDays: null,
    ...fields,
  };
}

const OTHERS: Row[] = [
  row("wms", {
    name: "Склад. Мобильный ТСД",
    customer: "АО «Логистика»",
    moderators: [morozov],
    presales: [sidorov],
    status: "completed",
    outcome: "won",
    figure: "p80",
    hours: "1840",
    currency: "RUB",
    quoteCur: "6120400",
    quoteRub: "6120400",
    contract: "5814000",
    createdDaysAgo: 98,
    updatedDaysAgo: 8,
    firstSnapshotDays: 6,
  }),
  row("edo", {
    name: "Интеграция с ЭДО",
    customer: "ПАО «Энерго»",
    moderators: [smirnova],
    presales: [userRef(belova)],
    status: "completed",
    outcome: "won",
    figure: "p90",
    hours: "620",
    currency: "RUB",
    quoteCur: "2180000",
    quoteRub: "2180000",
    contract: "1918000",
    createdDaysAgo: 80,
    updatedDaysAgo: 15,
    firstSnapshotDays: 4,
  }),
  row("market", {
    name: "Маркетплейс запчастей",
    customer: "ТОО «Авто-КЗ»",
    moderators: [morozov],
    presales: [userRef(belova)],
    status: "completed",
    outcome: "lost",
    lossReason: reason("price"),
    figure: "p80",
    hours: "2310.5",
    currency: "KZT",
    quoteCur: "42360000",
    quoteRub: "7836600",
    contract: null,
    createdDaysAgo: 70,
    updatedDaysAgo: 22,
    firstSnapshotDays: 9,
  }),
  row("bi", {
    name: "BI-отчётность",
    customer: "ООО «Ритейл»",
    moderators: [ivanov],
    presales: [],
    status: "consolidation",
    outcome: "unknown",
    figure: "e",
    hours: "390",
    currency: "RUB",
    quoteCur: "1053000",
    quoteRub: "1053000",
    contract: null,
    createdDaysAgo: 20,
    updatedDaysAgo: 3,
  }),
  row("chatbot", {
    name: "Чат-бот поддержки",
    customer: "ООО «Телеком»",
    moderators: [],
    presales: [sidorov],
    status: "estimation",
    outcome: "unknown",
    figure: "p80",
    hours: null,
    currency: "RUB",
    quoteCur: null,
    quoteRub: null,
    contract: null,
    createdDaysAgo: 30,
    updatedDaysAgo: 24,
  }),
  row("crm", {
    name: "CRM для агентства",
    customer: "ООО «Медиа»",
    moderators: [smirnova],
    presales: [sidorov],
    status: "completed",
    outcome: "won",
    figure: "p80",
    hours: "980",
    currency: "RUB",
    quoteCur: "3240000",
    quoteRub: "3240000",
    contract: "3240000",
    createdDaysAgo: 60,
    updatedDaysAgo: 5,
    firstSnapshotDays: 5,
  }),
  row("insurer", {
    name: "ЛК страхователя",
    customer: "АО «Страховой дом»",
    moderators: [orlova],
    presales: [userRef(belova)],
    status: "completed",
    outcome: "won",
    figure: "p80",
    hours: "1210",
    currency: "RUB",
    quoteCur: "4050000",
    quoteRub: "4050000",
    contract: "3766500",
    createdDaysAgo: 90,
    updatedDaysAgo: 10,
    firstSnapshotDays: 7,
  }),
  row("bank", {
    name: "Мобильный банк",
    customer: "АО «Финтех»",
    moderators: [morozov],
    presales: [sidorov],
    status: "completed",
    outcome: "lost",
    lossReason: reason("rival"),
    figure: "p90",
    hours: "3120",
    currency: "RUB",
    quoteCur: "10500000",
    quoteRub: "10500000",
    contract: null,
    createdDaysAgo: 110,
    updatedDaysAgo: 40,
    firstSnapshotDays: 12,
  }),
  row("procure", {
    name: "Портал закупок",
    customer: "ООО «Снабжение»",
    moderators: [smirnova],
    presales: [userRef(belova)],
    status: "completed",
    outcome: "lost",
    lossReason: reason("other"),
    lossText: "Заказчик заморозил бюджет до весны",
    figure: "p80",
    hours: "760",
    currency: "RUB",
    quoteCur: "2470000",
    quoteRub: "2470000",
    contract: null,
    createdDaysAgo: 50,
    updatedDaysAgo: 18,
    firstSnapshotDays: 8,
  }),
  row("assets", {
    name: "Учёт оборудования",
    customer: "АО «Энергосеть»",
    moderators: [orlova],
    presales: [],
    status: "archived",
    outcome: "cancelled",
    figure: "e",
    hours: "540",
    currency: "RUB",
    quoteCur: "1620000",
    quoteRub: "1620000",
    contract: null,
    createdDaysAgo: 100,
    updatedDaysAgo: 35,
    firstSnapshotDays: 10,
  }),
];

/** Проект есть только в реестре портфеля (у него нет дерева и настроек демо). */
export function isPortfolioOnly(id: string): boolean {
  return OTHERS.some((r) => r.id === id);
}

/** Настоящие демо-проекты: команда, часы и деньги — из данных проекта, итог — из «Результата». */
function realRows(): Row[] {
  return Object.values(PROJECTS).map((p) => {
    const members = p.members as { user: Ref; role: string }[];
    const o = outcomeOf(p);
    const fig = p.money.figures.p80;
    return {
      id: p.id,
      name: p.name,
      customer: p.customer,
      moderators: members
        .filter((m) => m.role === "moderator")
        .map((m) => m.user),
      presales: members.filter((m) => m.role === "presale").map((m) => m.user),
      status: (p as { status?: Status }).status ?? "estimation",
      outcome: o.outcome,
      lossReason: o.loss_reason_id,
      lossText: o.loss_reason_text,
      figure: "p80",
      hours: p.totals.total.p80 ?? p.totals.total.e,
      currency: p.money.currency,
      quoteCur: fig.total_cur,
      quoteRub: fig.total_rub,
      contract: o.money.contract_amount,
      createdDaysAgo: 14,
      updatedDaysAgo: p.key === "portal" ? 0 : 1,
      firstSnapshotDays: p.key === "portal" ? 11 : null,
    };
  });
}

/** Кто стал модератором за сессию демо: проект → пользователи. */
const joined = new Map<string, Ref[]>();

export function resetDemoPortfolio(): void {
  joined.clear();
}

function rows(): Row[] {
  return [...realRows(), ...OTHERS].map((r) => ({
    ...r,
    moderators: [...r.moderators, ...(joined.get(r.id) ?? [])],
  }));
}

const daysAgo = (days: number) => minutesAgo(days * 24 * 60);
const dateOf = (days: number) => daysAgo(days).slice(0, 10);

function item(r: Row) {
  return {
    id: r.id,
    name: r.name,
    customer: r.customer,
    moderators: r.moderators,
    presales: r.presales,
    status: r.status,
    outcome: r.outcome,
    quote_figure: r.figure,
    quote_hours: r.hours === null ? null : hours(r.hours),
    no_moderator: r.moderators.length === 0,
    created_at: daysAgo(r.createdDaysAgo),
    updated_at: daysAgo(r.updatedDaysAgo),
    money: {
      currency: r.currency,
      quote_cur: r.quoteCur,
      quote_rub: r.quoteRub,
      cost_rub: r.quoteRub,
      contract_amount: r.contract,
      rates_missing: r.quoteCur === null,
    },
  };
}

type Query = Record<string, string | undefined>;

function inPeriod(r: Row, from?: string, to?: string): boolean {
  const created = dateOf(r.createdDaysAgo);
  return (!from || created >= from) && (!to || created <= to);
}

/** Реестр с фильтрами FR-PORT-01; свежие изменения сверху. */
export function portfolioProjects(query: Query) {
  const q = (query.q ?? "").trim().toLowerCase();
  return rows()
    .filter((r) => inPeriod(r, query.from, query.to))
    .filter((r) => !query.status || r.status === query.status)
    .filter((r) => !query.outcome || r.outcome === query.outcome)
    .filter(
      (r) =>
        !query.moderator_id ||
        r.moderators.some((m) => m.id === query.moderator_id),
    )
    .filter(
      (r) =>
        !q ||
        r.name.toLowerCase().includes(q) ||
        r.customer.toLowerCase().includes(q),
    )
    .sort((a, b) => a.updatedDaysAgo - b.updatedDaysAgo)
    .map(item);
}

const sum = (values: (string | null)[]) =>
  values.reduce((acc, v) => acc + (v === null ? 0 : Number(v)), 0);

function median(values: number[]): number | null {
  if (values.length === 0) return null;
  const s = [...values].sort((a, b) => a - b);
  const mid = Math.floor(s.length / 2);
  return s.length % 2 ? (s[mid] ?? 0) : ((s[mid - 1] ?? 0) + (s[mid] ?? 0)) / 2;
}

const IN_WORK = new Set<Status>(["preparation", "estimation", "consolidation"]);

/** Сводка за период FR-PORT-02 по тем же проектам (период — по дате создания). */
export function portfolioSummary(query: Query) {
  const from = query.from ?? dateOf(120);
  const to = query.to ?? NOW.slice(0, 10);
  const period = rows().filter((r) => inPeriod(r, from, to));
  const count = <K extends string>(keys: K[]) => {
    const out: Record<string, number> = {};
    for (const k of keys) out[k] = (out[k] ?? 0) + 1;
    return out;
  };
  const won = period.filter((r) => r.outcome === "won");
  const lost = period.filter((r) => r.outcome === "lost");
  const decided = won.length + lost.length;
  const wonRub = sum(won.map((r) => r.quoteRub));
  const lostRub = sum(lost.map((r) => r.quoteRub));
  const ratios = won
    .filter((r) => r.contract !== null && r.quoteCur !== null)
    .map((r) => (Number(r.contract) / Number(r.quoteCur)) * 100);
  const reasons = new Map<string, { count: number; texts: string[] }>();
  for (const r of lost) {
    const key = r.lossReason ?? "";
    const entry = reasons.get(key) ?? { count: 0, texts: [] };
    entry.count += 1;
    if (r.lossText) entry.texts.push(r.lossText);
    reasons.set(key, entry);
  }
  const months = new Map<
    string,
    { won: number; lost: number; cancelled: number }
  >();
  for (const r of period) {
    const month = dateOf(r.createdDaysAgo).slice(0, 7);
    const m = months.get(month) ?? { won: 0, lost: 0, cancelled: 0 };
    if (r.outcome === "won") m.won += 1;
    if (r.outcome === "lost") m.lost += 1;
    if (r.outcome === "cancelled") m.cancelled += 1;
    months.set(month, m);
  }
  const pct = (v: number) => v.toFixed(1);
  const firstSnapshot = median(
    period.flatMap((r) =>
      r.firstSnapshotDays === null ? [] : [r.firstSnapshotDays],
    ),
  );
  const contractMedian = median(ratios);
  return {
    period: { from, to },
    by_status: count(period.map((r) => r.status)),
    by_outcome: count(period.map((r) => r.outcome)),
    won_share_count_pct: decided ? pct((won.length / decided) * 100) : null,
    won_share_money_pct:
      wonRub + lostRub ? pct((wonRub / (wonRub + lostRub)) * 100) : null,
    sum_won_cur: String(wonRub),
    sum_lost_cur: String(lostRub),
    sum_in_progress_cur: String(
      sum(period.filter((r) => IN_WORK.has(r.status)).map((r) => r.quoteRub)),
    ),
    loss_reasons: [...reasons.entries()]
      .map(([id, v]) => ({
        loss_reason_id: id || null,
        name: LOSS_REASONS.find((x) => x.id === id)?.name ?? "Без причины",
        count: v.count,
        texts: v.texts,
      }))
      .sort((a, b) => b.count - a.count),
    contract_to_quote_median_pct:
      contractMedian === null ? null : pct(contractMedian),
    by_month: [...months.entries()]
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([month, m]) => ({ month, ...m })),
    first_snapshot_median_days:
      firstSnapshot === null ? null : pct(firstSnapshot),
  };
}

/**
 * «Стать модератором проекта» (FR-PORT-03, R-06): только себя, не в «Архиве». Возвращает
 * список модераторов проекта или код ошибки.
 */
export function joinAsModerator(
  projectId: string,
  persona: Persona,
): { error: "NOT_FOUND" | "PROJECT_STATUS_CONFLICT" } | Ref[] {
  const r = rows().find((x) => x.id === projectId);
  if (!r) return { error: "NOT_FOUND" };
  if (r.status === "archived") return { error: "PROJECT_STATUS_CONFLICT" };
  const me = userRef(persona);
  if (!r.moderators.some((m) => m.id === personaId(persona)))
    joined.set(r.id, [...(joined.get(r.id) ?? []), me]);
  return [...r.moderators.filter((m) => m.id !== me.id), me];
}

// --- выгрузки ------------------------------------------------------------------------------

/** Задания выгрузки демо: готовы через 1,5 с после создания. */
const jobs = new Map<
  string,
  { kind: string; createdAt: number; name: string }
>();

export function createExport(kind: string, name: string) {
  const id = uuidFrom(
    "export",
    kind,
    String(jobs.size + 1),
    String(Date.now()),
  );
  jobs.set(id, { kind, createdAt: Date.now(), name });
  return exportJob(id);
}

export function exportJob(id: string) {
  const job = jobs.get(id);
  if (!job) return null;
  const ready = Date.now() - job.createdAt >= 1500;
  return {
    id,
    kind: job.kind,
    status: ready ? ("ready" as const) : ("pending" as const),
    file_name: ready ? job.name : null,
    download_url: ready ? `/api/v1/exports/${id}/download` : null,
    expires_at: new Date(job.createdAt + 24 * 3600_000)
      .toISOString()
      .replace(/\.\d{3}Z$/, "Z"),
  };
}
