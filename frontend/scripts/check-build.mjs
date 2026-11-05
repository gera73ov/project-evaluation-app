/**
 * INF-003 · проверка сборки (SEC-WEB-03): в dist/index.html нет inline-скриптов и
 * обработчиков событий, а сборка не ссылается на внешние адреса (CDN, шрифты).
 * Запускается после `vite build` в `npm run build`.
 */
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

/** Найти нарушения в HTML-странице. */
export function htmlProblems(html) {
  const problems = [];
  for (const m of html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/gi)) {
    const attrs = m[1] ?? '';
    if (!/\bsrc\s*=/.test(attrs)) problems.push('inline-скрипт без src');
    else if (m[2]?.trim()) problems.push('скрипт с src и телом');
    const src = attrs.match(/\bsrc\s*=\s*["']?([^"'\s>]+)/)?.[1] ?? '';
    if (/^(https?:)?\/\//i.test(src)) problems.push(`внешний скрипт ${src}`);
  }
  if (/\son[a-z]+\s*=/i.test(html)) problems.push('inline-обработчик события on*=');
  if (/javascript:/i.test(html)) problems.push('javascript: URL');
  for (const m of html.matchAll(/<link\b[^>]*href\s*=\s*["']?((https?:)?\/\/[^"'\s>]+)/gi)) {
    problems.push(`внешний ресурс ${m[1]}`);
  }
  return problems;
}

/** Найти внешние адреса загрузки в CSS (`@import`, `url()`). */
export function cssProblems(css) {
  const problems = [];
  for (const m of css.matchAll(/(@import\s+(?:url\()?|url\()\s*["']?((https?:)?\/\/[^"')\s]+)/gi)) {
    problems.push(`внешний ресурс в CSS ${m[2]}`);
  }
  return problems;
}

function walk(dir) {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    return statSync(path).isDirectory() ? walk(path) : [path];
  });
}

function main() {
  const dist = fileURLToPath(new URL('../dist/', import.meta.url));
  const problems = htmlProblems(readFileSync(join(dist, 'index.html'), 'utf8')).map(
    (p) => `index.html: ${p}`,
  );
  for (const file of walk(dist).filter((f) => f.endsWith('.css'))) {
    problems.push(...cssProblems(readFileSync(file, 'utf8')).map((p) => `${file}: ${p}`));
  }
  if (problems.length) {
    console.error(`Сборка нарушает SEC-WEB-03:\n- ${problems.join('\n- ')}`);
    process.exit(1);
  }
  console.log('check-build: inline-скриптов и внешних ресурсов нет');
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) main();
