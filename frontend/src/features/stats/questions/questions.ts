/**
 * FE-043 · правила вкладок «Вопросы заказчику» (SPEC 11.11, FR-CQ-02…04, BR-CQ-01/02) и
 * «Обсуждения» (11.10): номер В-NNN, числа на чипах, выбор по умолчанию, «ждём N дней», какие
 * действия доступны.
 */
import type { components } from '../../../shared/api/client';

type CustomerQuestion = components['schemas']['CustomerQuestion'];
type Thread = components['schemas']['Thread'];
export type CustomerStatus = components['schemas']['CustomerStatus'];

export const CQ_STATUSES: readonly CustomerStatus[] = ['new', 'sent', 'answered', 'closed', 'withdrawn'];

/** «В-006»: номер выдаётся при создании и не переиспользуется (FR-CQ-02). */
export function questionNo(no: number | null): string {
  return no === null ? 'В-—' : `В-${String(no).padStart(3, '0')}`;
}

/** Числа на чипах: все и по каждому статусу. */
export function countByStatus(items: readonly CustomerQuestion[]): Map<CustomerStatus | 'all', number> {
  const out = new Map<CustomerStatus | 'all', number>([['all', items.length]]);
  for (const s of CQ_STATUSES) out.set(s, 0);
  for (const q of items) {
    const s = q.thread.customer_status;
    if (s) out.set(s, (out.get(s) ?? 0) + 1);
  }
  return out;
}

/** По умолчанию к выгрузке отмечены все «новые» (11.11 №2). */
export function defaultSelection(items: readonly CustomerQuestion[]): string[] {
  return items.filter((q) => q.thread.customer_status === 'new').map((q) => q.thread.id);
}

/** Сколько полных дней вопрос ждёт ответа после отправки. */
export function waitingDays(sentAt: string, now: Date): number {
  return Math.max(0, Math.floor((now.getTime() - new Date(sentAt).getTime()) / 86_400_000));
}

/** Дата для плашки статуса: «отправлен 02.11», «отвечен 02.11», «решён 30.10». */
export function statusDate(thread: Thread): string | null {
  switch (thread.customer_status) {
    case 'sent':
      return thread.sent_at;
    case 'answered':
      return thread.answered_at;
    case 'closed':
      return thread.closed_at ?? thread.resolved_at;
    default:
      return null;
  }
}

export interface CqActions {
  answer: boolean;
  withdraw: boolean;
}

/**
 * Действия строки: «Внести ответ заказчика» — отправленному вопросу при `cq.answer` (FR-CQ-03);
 * «Снять» — новому (автору или пресейлу/модератору) и отправленному (только пресейлу/модератору,
 * BR-CQ-01). Окончательно права проверяет сервер.
 */
export function cqActions(thread: Thread, perms: readonly string[], meId: string | null): CqActions {
  const s = thread.customer_status;
  const manager = perms.includes('cq.manage');
  const own = meId !== null && thread.opened_by.id === meId;
  return {
    answer: s === 'sent' && perms.includes('cq.answer'),
    withdraw: perms.includes('cq.withdraw') && ((s === 'new' && (own || manager)) || (s === 'sent' && manager)),
  };
}

/** Путь узла вопроса; пустой путь — вопрос по проекту целиком. */
export function pathLabel(path: readonly string[], whole: string): string {
  return path.length === 0 ? whole : path.join(' › ');
}

/** Адресаты первого сообщения обсуждения: подписи для колонки «Кому». */
export function addresseeKinds(thread: Thread): string[] {
  return [...new Set(thread.first_message.addressees.map((a) => a.target_type))];
}
