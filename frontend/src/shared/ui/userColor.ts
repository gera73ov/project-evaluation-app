/**
 * Цвет пользователя (DESIGN.md 2.6): аватар, рамка занятой ячейки, метка автора, присутствие.
 * Детерминированно `palette[hash(user_id) % 10]`, чтобы у человека цвет был одинаков везде; цвет
 * из события сервера (`UserRef.color`) главнее. Рядом с цветом всегда инициалы (FR-UI-04).
 */
export const USER_PALETTE = [
  '#557a9a',
  '#a8661e',
  '#5e7f4f',
  '#437f7f',
  '#9c6a2e',
  '#7f62a6',
  '#9a5a8a',
  '#7a6a5a',
  '#a0605a',
  '#8a5a44',
] as const;

/** Простой 32-битный хэш строки (FNV-1a). */
function hash(text: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return h >>> 0;
}

export function userColor(user: { id: string; color?: string | undefined }): string {
  return user.color ?? USER_PALETTE.at(hash(user.id) % USER_PALETTE.length) ?? USER_PALETTE[0];
}
