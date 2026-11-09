/**
 * FE-030 · текст сообщения (FR-DISC-02, SEC-WEB-02): только как текст, переводы строк сохраняются
 * CSS, ссылки `http(s)://` — `<a target="_blank" rel="noopener noreferrer">`. HTML и Markdown не
 * интерпретируются: React экранирует строки сам, `dangerouslySetInnerHTML` не используется.
 */
import type { ReactNode } from 'react';

/** Конец ссылки: пробел или символы, которые не бывают её частью. */
const STOP = new Set([' ', '\n', '\t', '\r', '<', '>', '"', '«', '»']);
/** Знаки препинания в конце ссылки относятся к тексту: «см. https://x.ru/a.» */
const TRAILING = new Set(['.', ',', ';', ':', '!', '?', ')']);

/** Части текста: строки и ссылки. */
export function splitLinks(text: string): ({ text: string } | { href: string })[] {
  const out: ({ text: string } | { href: string })[] = [];
  let from = 0;
  let i = 0;
  while (i < text.length) {
    const rest = text.slice(i, i + 8).toLowerCase();
    const scheme = rest.startsWith('https://') ? 8 : rest.startsWith('http://') ? 7 : 0;
    if (!scheme) {
      i += 1;
      continue;
    }
    let end = i + scheme;
    while (end < text.length && !STOP.has(text.charAt(end))) end += 1;
    while (end > i + scheme && TRAILING.has(text.charAt(end - 1))) end -= 1;
    if (end === i + scheme) {
      i = end;
      continue;
    }
    if (i > from) out.push({ text: text.slice(from, i) });
    out.push({ href: text.slice(i, end) });
    from = end;
    i = end;
  }
  if (from < text.length) out.push({ text: text.slice(from) });
  return out;
}

export function Linkify({ text }: { text: string }) {
  const parts: ReactNode[] = splitLinks(text).map((part, i) =>
    'href' in part ? (
      <a key={i} href={part.href} target="_blank" rel="noopener noreferrer">
        {part.href}
      </a>
    ) : (
      part.text
    ),
  );
  return <>{parts}</>;
}
