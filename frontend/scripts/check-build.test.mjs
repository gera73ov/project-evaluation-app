// @vitest-environment node
import { describe, expect, it } from 'vitest';

import { cssProblems, htmlProblems } from './check-build.mjs';

describe('check-build (SEC-WEB-03)', () => {
  it('пропускает чистую сборку', () => {
    const html =
      '<html><head><script type="module" crossorigin src="/assets/index-1.js"></script>' +
      '<link rel="stylesheet" href="/assets/index-1.css"></head><body><div id="root"></div></body></html>';
    expect(htmlProblems(html)).toEqual([]);
    expect(cssProblems('a{background:url(/assets/x.png)}')).toEqual([]);
  });

  it.each([
    ['<script>alert(1)</script>', 'inline-скрипт без src'],
    ['<script src="/a.js">x()</script>', 'скрипт с src и телом'],
    ['<script src="https://cdn.example/a.js"></script>', 'внешний скрипт'],
    ['<img src=x onerror="x()">', 'inline-обработчик'],
    ['<a href="javascript:x()">', 'javascript:'],
    ['<link rel="stylesheet" href="//fonts.example/css">', 'внешний ресурс'],
  ])('ловит %s', (html, problem) => {
    expect(htmlProblems(html).join(';')).toContain(problem);
  });

  it('ловит внешние шрифты в CSS', () => {
    expect(cssProblems('@import url("https://fonts.googleapis.com/css2?x");')).toHaveLength(1);
    expect(cssProblems("@font-face{src:url('//cdn.example/f.woff2')}")).toHaveLength(1);
  });
});
