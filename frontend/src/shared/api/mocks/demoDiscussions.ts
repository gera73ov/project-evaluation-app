/**
 * FE-030 · обсуждения в демо (FR-DISC-01…09, FR-CQ-03): лента «Обмена с 1С» как на `work.png`
 * (вопрос заказчику, серые события, ответ заказчика) и всё, что написано за сессию. Правки,
 * отзывы и закрытие вопросов живут до перезагрузки страницы.
 */
import {
  DISCIPLINES,
  PEOPLE,
  disciplineId,
  userRef,
  type DemoProject,
} from "./data";
import { uuidFrom } from "./ids";
import { PERSONAS } from "./personas";

type UserRef = ReturnType<typeof userRef>;
type Addressee = { target_type: string; target_id: string | null };

export type DemoMessage = {
  id: string;
  thread_id: string | null;
  node_id: string | null;
  author: UserRef | null;
  kind: "message" | "event" | "customer_answer";
  body: string;
  event: Record<string, unknown> | null;
  needs_answer: boolean;
  addressees: Addressee[];
  created_at: string;
  edited_at: string | null;
  revoked: boolean;
};

export type DemoThread = {
  id: string;
  node_id: string | null;
  opened_by: UserRef;
  status: "open" | "resolved";
  resolved_by: UserRef | null;
  resolved_at: string | null;
  is_customer: boolean;
  customer_question_no: number | null;
  customer_status: string | null;
  sent_at: string | null;
  answered_at: string | null;
  closed_at: string | null;
  withdraw_reason: string | null;
  edited_after_sent: boolean;
};

/** Сообщения и вопросы, созданные за сессию. */
const posted: DemoMessage[] = [];
const opened: DemoThread[] = [];
/** Правки сообщений и вопросов демо и сессии. */
const messageEdits = new Map<string, Partial<DemoMessage>>();
const threadEdits = new Map<string, Partial<DemoThread>>();
let counter = 0;

export function resetDemoDiscussions(): void {
  notes.length = 0;
  noteEdits.clear();
  posted.length = 0;
  opened.length = 0;
  messageEdits.clear();
  threadEdits.clear();
  counter = 0;
}

const nodeId = (key: string) => uuidFrom("node", "portal", key);
const at = (iso: string) => `${iso}:00Z`;

const message = (
  key: string,
  fields: Partial<DemoMessage> & Pick<DemoMessage, "created_at">,
): DemoMessage => ({
  id: uuidFrom("message", "portal", key),
  thread_id: null,
  node_id: nodeId("n-1c"),
  author: null,
  kind: "message",
  body: "",
  event: null,
  needs_answer: false,
  addressees: [],
  edited_at: null,
  revoked: false,
  ...fields,
});

const Q_1C = uuidFrom("thread", "portal", "1c-protocol");

/** Лента «Обмена с 1С» (11.4 №13–14): 5 записей, 3 сообщения. */
function seededMessages(p: DemoProject): DemoMessage[] {
  if (p.key !== "portal") return [];
  return [
    message("1c-arch", {
      author: userRef(PEOPLE.morozov),
      body: "Есть ли у заказчика готовый API для 1С или интеграцию делаем с нуля?",
      created_at: at("2026-10-30T10:05"),
    }),
    message("1c-comment", {
      author: userRef(PERSONAS.expert),
      kind: "event",
      event: { action: "update", changes: { comment: ["", "Допущение…"] } },
      created_at: at("2026-10-31T09:12"),
    }),
    message("1c-question", {
      thread_id: Q_1C,
      author: userRef(PERSONAS.expert),
      body: "Какой протокол обмена с 1С: REST, SOAP или файловый обмен? Есть ли спецификация?",
      needs_answer: true,
      addressees: [{ target_type: "customer", target_id: null }],
      created_at: at("2026-11-01T11:05"),
    }),
    message("1c-orp", {
      author: userRef(PERSONAS.expert),
      kind: "event",
      event: {
        action: "update",
        changes: { o: ["30", "40"], r: ["40", "60"], p: ["60", "100"] },
      },
      created_at: at("2026-11-01T11:07"),
    }),
    message("1c-answer", {
      thread_id: Q_1C,
      author: userRef(PERSONAS.presale),
      kind: "customer_answer",
      body: "REST. Спецификации пока нет, обещают в декабре.",
      created_at: at("2026-11-02T16:40"),
    }),
  ];
}

function seededThreads(p: DemoProject): DemoThread[] {
  if (p.key !== "portal") return [];
  return [
    {
      id: Q_1C,
      node_id: nodeId("n-1c"),
      opened_by: userRef(PERSONAS.expert),
      status: "open",
      resolved_by: null,
      resolved_at: null,
      is_customer: true,
      customer_question_no: 7,
      customer_status: "answered",
      sent_at: at("2026-11-01T12:00"),
      answered_at: at("2026-11-02T16:40"),
      closed_at: null,
      withdraw_reason: null,
      edited_after_sent: false,
    },
  ];
}

function allMessages(p: DemoProject): DemoMessage[] {
  return [
    ...seededMessages(p),
    ...posted.filter((m) => projectOfMessage.get(m.id) === p),
  ].map((m) => ({ ...m, ...messageEdits.get(m.id) }));
}

function allThreads(p: DemoProject): DemoThread[] {
  return [
    ...seededThreads(p),
    ...opened.filter((t) => projectOfThread.get(t.id) === p),
  ].map((t) => ({ ...t, ...threadEdits.get(t.id) }));
}

const projectOfMessage = new Map<string, DemoProject>();
const projectOfThread = new Map<string, DemoProject>();

function withMessage(p: DemoProject, thread: DemoThread) {
  const messages = allMessages(p).filter((m) => m.thread_id === thread.id);
  const first = messages.find((m) => m.kind === "message") ?? messages[0];
  return {
    ...thread,
    first_message: first ?? null,
    replies_count: Math.max(0, messages.length - 1),
  };
}

/** `GET /nodes/{id}/messages`: лента по времени и вопросы узла. */
/** Лента узла; `null` — обсуждение проекта (CR-007). */
export function nodeFeed(p: DemoProject, id: string | null) {
  const items = allMessages(p).filter((m) => m.node_id === id);
  const threads = allThreads(p)
    .filter((t) => t.node_id === id)
    .map((t) => withMessage(p, t));
  return {
    items: items.sort((a, b) => a.created_at.localeCompare(b.created_at)),
    threads,
    next_cursor: null,
  };
}

function nextId(kind: string) {
  counter += 1;
  return uuidFrom(kind, "demo", String(counter));
}

type Body = Record<string, unknown>;

const addresseesOf = (body: Body): Addressee[] =>
  Array.isArray(body.addressees) ? (body.addressees as Addressee[]) : [];

/** `POST /nodes/{id}/messages`: с «нужен ответ» открывает вопрос (FR-DISC-09). */
export function postMessage(
  p: DemoProject,
  node: string | null,
  body: Body,
  author: UserRef,
  threadId: string | null = null,
): DemoMessage {
  const needs = body.needs_answer === true && threadId === null;
  const addressees = addresseesOf(body);
  let thread = threadId;
  if (needs) {
    const customer = addressees.some((a) => a.target_type === "customer");
    const created: DemoThread = {
      id: nextId("thread"),
      node_id: node,
      opened_by: author,
      status: "open",
      resolved_by: null,
      resolved_at: null,
      is_customer: customer,
      customer_question_no: customer ? 100 + counter : null,
      customer_status: customer ? "new" : null,
      sent_at: null,
      answered_at: null,
      closed_at: null,
      withdraw_reason: null,
      edited_after_sent: false,
    };
    opened.push(created);
    projectOfThread.set(created.id, p);
    thread = created.id;
  }
  const msg: DemoMessage = {
    id: nextId("message"),
    thread_id: thread,
    node_id: node,
    author,
    kind: "message",
    body: String(body.body ?? ""),
    event: null,
    needs_answer: needs,
    addressees,
    created_at: new Date().toISOString(),
    edited_at: null,
    revoked: false,
  };
  posted.push(msg);
  projectOfMessage.set(msg.id, p);
  return msg;
}

/** `POST /threads/{id}/messages`: ответ в вопрос. */
export function replyThread(
  p: DemoProject,
  threadId: string,
  body: Body,
  author: UserRef,
) {
  const thread = allThreads(p).find((t) => t.id === threadId);
  if (!thread) return undefined;
  return postMessage(p, thread.node_id, body, author, thread.id);
}

/** `PATCH /messages/{id}` и `POST /messages/{id}/revoke` (FR-DISC-06). */
export function editMessage(
  p: DemoProject,
  id: string,
  change: { body: string } | { revoked: true },
) {
  const msg = allMessages(p).find((m) => m.id === id);
  if (!msg) return undefined;
  const fields: Partial<DemoMessage> =
    "revoked" in change
      ? { revoked: true, body: "" }
      : { body: change.body, edited_at: new Date().toISOString() };
  messageEdits.set(id, { ...messageEdits.get(id), ...fields });
  return { ...msg, ...fields };
}

/** `POST /threads/{id}/resolve` и `/reopen` (FR-DISC-05). */
export function setThreadStatus(
  p: DemoProject,
  id: string,
  resolved: boolean,
  by: UserRef,
) {
  const thread = allThreads(p).find((t) => t.id === id);
  if (!thread) return undefined;
  const now = new Date().toISOString();
  const fields: Partial<DemoThread> = resolved
    ? {
        status: "resolved",
        resolved_by: by,
        resolved_at: now,
        ...(thread.is_customer
          ? { customer_status: "closed", closed_at: now }
          : {}),
      }
    : {
        status: "open",
        resolved_by: null,
        resolved_at: null,
        ...(thread.is_customer
          ? { customer_status: "answered", closed_at: null }
          : {}),
      };
  threadEdits.set(id, { ...threadEdits.get(id), ...fields });
  return withMessage(p, { ...thread, ...fields });
}

/** `GET /projects/{id}/members/suggest?q=` (FR-DISC-03): дисциплины, участники, модератор, заказчик. */
export function suggest(p: DemoProject, q: string) {
  const all = [
    ...p.disciplines.map((key) => ({
      target_type: "discipline",
      target_id: disciplineId(key),
      label: DISCIPLINES.find((d) => d.key === key)?.name ?? key,
    })),
    ...(p.members as { user: UserRef; status?: string }[])
      .filter((m) => m.status !== "blocked")
      .map((m) => ({
        target_type: "user",
        target_id: m.user.id,
        label: m.user.full_name,
      })),
    { target_type: "moderators", target_id: null, label: "модератор" },
    { target_type: "customer", target_id: null, label: "заказчик" },
  ];
  const seen = new Set<string>();
  const needle = q.trim().toLocaleLowerCase("ru");
  return all
    .filter((item) => {
      const key = `${item.target_type}/${item.target_id ?? ""}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return (
        !needle ||
        item.label
          .toLocaleLowerCase("ru")
          .split(/[\s.]+/)
          .some((word) => word.startsWith(needle)) ||
        item.label.toLocaleLowerCase("ru").startsWith(needle)
      );
    })
    .slice(0, 10);
}

// --- FE-031: закрытые заметки --------------------------------------------------------------

type DemoNote = {
  id: string;
  node_id: string | null;
  author: UserRef;
  body: string;
  created_at: string;
  edited_at: string | null;
};

const notes: (DemoNote & { project: DemoProject })[] = [];
const noteEdits = new Map<string, Partial<DemoNote>>();

/** Заметки «Обмена с 1С» как на `work.png` (11.4 №18). */
function seededNotes(p: DemoProject): DemoNote[] {
  if (p.key !== "portal") return [];
  return [
    {
      id: uuidFrom("note", "portal", "1c-presale"),
      node_id: nodeId("n-1c"),
      author: userRef(PERSONAS.presale),
      body: "Заказчик торгуется по интеграции. Держим P80, скидку даём только за счёт УП.",
      created_at: at("2026-11-02T17:05"),
      edited_at: null,
    },
    {
      id: uuidFrom("note", "portal", "1c-moderator"),
      node_id: nodeId("n-1c"),
      author: userRef(PERSONAS.moderator),
      body: "Согласна. Если спецификации 1С не будет до 15.12 — вынести интеграцию отдельным этапом.",
      created_at: at("2026-11-02T17:20"),
      edited_at: null,
    },
  ];
}

function allNotes(p: DemoProject): DemoNote[] {
  return [
    ...seededNotes(p),
    ...notes
      .filter((n) => n.project === p)
      .map((n) => ({
        id: n.id,
        node_id: n.node_id,
        author: n.author,
        body: n.body,
        created_at: n.created_at,
        edited_at: n.edited_at,
      })),
  ].map((n) => ({ ...n, ...noteEdits.get(n.id) }));
}

/** `GET /projects/{id}/notes?node_id=`: без `node_id` — заметки проекта. */
export function listNotes(p: DemoProject, node: string | null) {
  return {
    items: allNotes(p)
      .filter((n) => n.node_id === node)
      .sort((a, b) => a.created_at.localeCompare(b.created_at)),
    next_cursor: null,
  };
}

export function createNote(p: DemoProject, body: Body, author: UserRef) {
  const note = {
    id: nextId("note"),
    node_id: typeof body.node_id === "string" ? body.node_id : null,
    author,
    body: String(body.body ?? ""),
    created_at: new Date().toISOString(),
    edited_at: null,
  };
  notes.push({ ...note, project: p });
  return note;
}

export function patchNote(p: DemoProject, id: string, body: Body) {
  const note = allNotes(p).find((n) => n.id === id);
  if (!note) return undefined;
  const fields = {
    body: String(body.body ?? ""),
    edited_at: new Date().toISOString(),
  };
  noteEdits.set(id, fields);
  return { ...note, ...fields };
}
