/**
 * FE-073 · сессии режима поддержки (FR-ADM-06, permissions.yaml support_session): администратор
 * открывает проект с причиной на 60 минут; пока сессия жива, проект доступен ему только на чтение,
 * без денег и заметок. Ключ — ключ демо-проекта или id проекта без демо-данных.
 */
const MINUTES = 60;

type Session = { id: string; reason: string; expiresAt: number };

const sessions = new Map<string, Session>();

export function resetDemoSupport() {
  sessions.clear();
}

export function open(key: string, id: string, reason: string) {
  const s = { id, reason, expiresAt: Date.now() + MINUTES * 60_000 };
  sessions.set(key, s);
  return s;
}

/** Живая сессия проекта или null (истёкшая удаляется). */
export function active(key: string): Session | null {
  const s = sessions.get(key);
  if (!s) return null;
  if (s.expiresAt <= Date.now()) {
    sessions.delete(key);
    return null;
  }
  return s;
}
