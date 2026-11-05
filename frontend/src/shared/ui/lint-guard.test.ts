// @vitest-environment node
/**
 * INF-003: линтер падает на dangerouslySetInnerHTML (SEC-WEB-02) и на eval.
 * Тест запускает настоящий конфиг eslint.config.js на фрагментах кода.
 */
import { ESLint } from 'eslint';
import { describe, expect, it } from 'vitest';

const eslint = new ESLint({ cwd: new URL('../../..', import.meta.url).pathname });

async function errors(code: string): Promise<string[]> {
  const [result] = await eslint.lintText(code, { filePath: 'src/features/guard/Sample.tsx' });
  return (result?.messages ?? []).filter((m) => m.severity === 2).map((m) => m.ruleId ?? '');
}

describe('ESLint guards', () => {
  it('JSX-атрибут dangerouslySetInnerHTML — ошибка', async () => {
    const ids = await errors(
      'export const X = ({ h }: { h: string }) => <div dangerouslySetInnerHTML={{ __html: h }} />;\n',
    );
    expect(ids).toContain('react/no-danger');
  });

  it('dangerouslySetInnerHTML через объект пропсов — ошибка', async () => {
    const ids = await errors(
      "import { createElement } from 'react';\n" +
        "export const X = (h: string) => createElement('div', { dangerouslySetInnerHTML: { __html: h } });\n",
    );
    expect(ids).toContain('no-restricted-syntax');
  });

  it('innerHTML и eval — ошибка', async () => {
    const ids = await errors(
      'export function f(el: HTMLElement, s: string) {\n  el.innerHTML = s;\n  return eval(s);\n}\n',
    );
    expect(ids).toEqual(expect.arrayContaining(['no-restricted-syntax', 'no-eval']));
  });

  it('обычный компонент проходит', async () => {
    expect(await errors('export const X = ({ t }: { t: string }) => <p>{t}</p>;\n')).toEqual([]);
  });
});
