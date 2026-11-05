/** FE-001 · детерминированные UUID и время демо-данных: одинаковые в каждом запуске моков. */

/** UUID (вид v7) из имени объекта: `uuidFrom('project', 'portal')`. Хэш FNV-1a, не криптография. */
export function uuidFrom(...parts: string[]): string {
  const text = parts.join('/');
  let hex = '';
  for (let round = 0; hex.length < 32; round += 1) {
    let h = 0x811c9dc5 ^ round;
    for (let i = 0; i < text.length; i += 1) {
      h ^= text.charCodeAt(i);
      h = Math.imul(h, 0x01000193) >>> 0;
    }
    hex += h.toString(16).padStart(8, '0');
  }
  const variant = ((parseInt(hex[16] ?? '0', 16) & 0x3) | 0x8).toString(16);
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-7${hex.slice(13, 16)}-${variant}${hex.slice(17, 20)}-${hex.slice(20, 32)}`;
}

/** «Сейчас» демо-данных — день, на который нарисованы макеты SPEC 11. */
export const NOW = '2026-11-05T11:20:00Z';
export const TODAY = '2026-11-05';

/** Момент на `minutes` минут раньше NOW. */
export function minutesAgo(minutes: number): string {
  return new Date(Date.parse(NOW) - minutes * 60_000).toISOString().replace('.000Z', 'Z');
}
