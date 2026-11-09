/**
 * FE-030 · лента обсуждения узла (FR-DISC-04…09): записи `listNodeMessages` → строки панели.
 *
 * - Закрытый вопрос сворачивается в одну строку «Решено: <начало вывода> · кто, когда» на месте
 *   своего первого сообщения (FR-DISC-05); остальные записи идут по времени.
 * - Серые события (FR-DISC-07) — `kind = event`, поля `event.changes = {поле: [было, стало]}`.
 * - Свои сообщения правятся, пока на них никто не ответил (FR-DISC-06).
 */
import type { components } from '../../shared/api/client';

export type Message = components['schemas']['Message'];
export type Thread = components['schemas']['Thread'];
export type Addressee = components['schemas']['Addressee'];

export type Entry =
  | { kind: 'message'; message: Message; thread: Thread | undefined }
  | { kind: 'event'; message: Message }
  | { kind: 'resolved'; thread: Thread; last: Message | undefined };

/** Записи ленты по времени; закрытые вопросы — одной строкой. */
export function feedEntries(items: readonly Message[], threads: readonly Thread[]): Entry[] {
  const byId = new Map(threads.map((t) => [t.id, t]));
  const out: Entry[] = [];
  const folded = new Set<string>();
  for (const message of items) {
    const thread = message.thread_id ? byId.get(message.thread_id) : undefined;
    if (thread?.status === 'resolved') {
      if (folded.has(thread.id)) continue;
      folded.add(thread.id);
      const own = items.filter((m) => m.thread_id === thread.id && m.kind !== 'event' && !m.revoked);
      out.push({ kind: 'resolved', thread, last: own.at(-1) });
      continue;
    }
    out.push(message.kind === 'event' ? { kind: 'event', message } : { kind: 'message', message, thread });
  }
  return out;
}

/** Ключ записи для React. */
export function entryKey(entry: Entry): string {
  return entry.kind === 'resolved' ? `t-${entry.thread.id}` : entry.message.id;
}

/** Можно ли править своё сообщение: никто другой не написал после него в том же вопросе или ленте. */
export function canEditMessage(message: Message, items: readonly Message[], me: string | null): boolean {
  if (!me || message.author?.id !== me || message.revoked || message.kind !== 'message') return false;
  const at = items.indexOf(message);
  return !items
    .slice(at + 1)
    .some((m) => m.kind !== 'event' && m.thread_id === message.thread_id && m.author?.id !== me);
}

/** Вопрос, на который по умолчанию идёт ответ: самый новый открытый. */
export function defaultThread(threads: readonly Thread[]): Thread | undefined {
  return threads
    .filter((t) => t.status === 'open')
    .sort((a, b) => b.first_message.created_at.localeCompare(a.first_message.created_at))[0];
}

type Changes = ReadonlyMap<string, readonly [unknown, unknown]>;

function changesOf(message: Message): Changes {
  const raw: unknown = message.event ? new Map(Object.entries(message.event)).get('changes') : undefined;
  if (!raw || typeof raw !== 'object') return new Map();
  return new Map(
    Object.entries(raw).flatMap(([field, pair]) =>
      Array.isArray(pair) && pair.length === 2 ? [[field, [pair[0], pair[1]] as const]] : [],
    ),
  );
}

const show = (v: unknown) => (v === null || v === undefined || v === '' ? '—' : String(v as string | number));

export interface EventPart {
  /** Ключ подписи в `discussion.ev.*`. */
  label: string;
  before?: string;
  after?: string;
}

/**
 * Что изменилось в сером событии: «O/R/P 30–40–60 → 40–60–100», «×N 1 → 3», «комментарий»,
 * «тип», «перенос». O/R/P собираются в одну вилку; неизменённая часть вилки — «·».
 */
export function eventParts(message: Message): EventPart[] {
  const changes = changesOf(message);
  const parts: EventPart[] = [];
  const fork = ['o', 'r', 'p'] as const;
  if (fork.some((f) => changes.has(f))) {
    const side = (i: 0 | 1) =>
      fork
        .map((f) => {
          const pair = changes.get(f);
          return pair ? show(i === 0 ? pair[0] : pair[1]) : '·';
        })
        .join('–');
    parts.push({ label: 'orp', before: side(0), after: side(1) });
  }
  const multiplier = changes.get('multiplier');
  if (multiplier) parts.push({ label: 'multiplier', before: show(multiplier[0]), after: show(multiplier[1]) });
  if (changes.has('comment') || changes.has('comment_lines')) parts.push({ label: 'comment' });
  if (changes.has('type_id')) parts.push({ label: 'type' });
  if (changes.has('parent_id')) parts.push({ label: 'move' });
  if (changes.has('title')) {
    const title = changes.get('title');
    parts.push({ label: 'title', before: show(title?.[0]), after: show(title?.[1]) });
  }
  if (!parts.length) parts.push({ label: 'other' });
  return parts;
}

/** Адресаты, чьи `@Метка` остались в тексте (стёртые из текста — не адресаты). */
export function keptAddressees(body: string, picked: readonly { addressee: Addressee; label: string }[]): Addressee[] {
  const seen = new Set<string>();
  return picked
    .filter((p) => body.includes(`@${p.label}`))
    .map((p) => p.addressee)
    .filter((a) => {
      const key = `${a.target_type}/${a.target_id ?? ''}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
}

/** Слово после `@` перед курсором: `@Бэк` → «Бэк»; нет — null. */
export function mentionAt(text: string, caret: number): { query: string; from: number } | null {
  const before = text.slice(0, caret);
  const at = before.lastIndexOf('@');
  if (at < 0) return null;
  if (at > 0 && !/\s/.test(before.charAt(at - 1))) return null;
  const query = before.slice(at + 1);
  if (query.length > 30 || /[\s@]/.test(query)) return null;
  return { query, from: at };
}
