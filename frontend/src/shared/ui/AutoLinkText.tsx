/**
 * FE-004 · текст с автоссылками (FR-DISC-02, SEC-WEB-02): ссылками становятся только `http://` и
 * `https://`; `javascript:`, `data:` и прочие схемы остаются текстом. HTML не интерпретируется.
 */
import { Fragment } from 'react';

const URL_RE = /\bhttps?:\/\/[^\s<>"']+/gi;
const TRAILING = /[.,;:!?)\]]+$/;

export interface TextPart {
  text: string;
  href: string | null;
}

export function splitLinks(text: string): TextPart[] {
  const parts: TextPart[] = [];
  let last = 0;
  for (const match of text.matchAll(URL_RE)) {
    const start = match.index;
    let url = match[0];
    const tail = TRAILING.exec(url)?.[0] ?? '';
    url = url.slice(0, url.length - tail.length);
    if (start > last) parts.push({ text: text.slice(last, start), href: null });
    parts.push({ text: url, href: safeHref(url) });
    last = start + url.length;
  }
  if (last < text.length) parts.push({ text: text.slice(last), href: null });
  return parts;
}

/** Только http/https; иначе null (ссылка не создаётся). */
export function safeHref(url: string): string | null {
  try {
    const parsed = new URL(url);
    return parsed.protocol === 'http:' || parsed.protocol === 'https:' ? parsed.href : null;
  } catch {
    return null;
  }
}

export function AutoLinkText({ text }: { text: string }) {
  return (
    <>
      {splitLinks(text).map((part, i) => (
        <Fragment key={i}>
          {part.href ? (
            <a href={part.href} target="_blank" rel="noopener noreferrer nofollow">
              {part.text}
            </a>
          ) : (
            part.text
          )}
        </Fragment>
      ))}
    </>
  );
}
