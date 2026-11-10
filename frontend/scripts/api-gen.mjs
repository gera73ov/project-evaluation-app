/**
 * API-006 · генерация TS-типов из contracts/openapi.yaml (SPEC 15.1, 13.1).
 *
 *   npm run api:gen         — записать src/shared/api/generated/schema.ts
 *   npm run api:gen:check   — проверить, что файл совпадает с контрактом (CI)
 *
 * FE-065: тем же запуском из contracts/audit-events.yaml пишется
 * src/shared/api/generated/audit-events.ts — категории и названия событий для фильтров журнала аудита.
 *
 * Схемы с `x-ts-type: DecimalString` (DecimalString, HoursString, MoneyString) становятся
 * branded-типом DecimalString из src/shared/api/decimal.ts: десятичные значения в API —
 * строки (contracts/api-conventions.md 2.1), а смешать их с обычной строкой нельзя.
 */
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { dirname, join, relative } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import openapiTS, { astToString } from 'openapi-typescript';
import ts from 'typescript';
import { parse } from 'yaml';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
export const CONTRACT = join(ROOT, '..', 'contracts', 'openapi.yaml');
export const OUTPUT = join(ROOT, 'src', 'shared', 'api', 'generated', 'schema.ts');

export const AUDIT_CONTRACT = join(ROOT, '..', 'contracts', 'audit-events.yaml');
export const AUDIT_OUTPUT = join(ROOT, 'src', 'shared', 'api', 'generated', 'audit-events.ts');

/** Каталог событий аудита: категории (кто видит) и события (категория, название). */
export function generateAuditEvents(contract = AUDIT_CONTRACT) {
  const doc = parse(readFileSync(contract, 'utf8'));
  const categories = Object.fromEntries(
    Object.entries(doc.categories).map(([k, v]) => [k, { title: v.title, visible_to: v.visible_to }]),
  );
  const events = Object.fromEntries(
    Object.entries(doc.events).map(([k, v]) => [k, { category: v.category, title: v.title }]),
  );
  return `/**
 * СГЕНЕРИРОВАНО из contracts/audit-events.yaml командой \`npm run api:gen\` (FE-065). Не править вручную.
 */
export type AuditCategory = { title: string; visible_to: readonly string[] };
export type AuditEvent = { category: string; title: string };

export const AUDIT_CATEGORIES: Readonly<Record<string, AuditCategory>> = ${JSON.stringify(categories, null, 2)};

export const AUDIT_EVENTS: Readonly<Record<string, AuditEvent>> = ${JSON.stringify(events, null, 2)};
`;
}

const HEADER = `/**
 * СГЕНЕРИРОВАНО из contracts/openapi.yaml командой \`npm run api:gen\` (API-006). Не править вручную:
 * CI сверяет файл с контрактом (\`npm run api:gen:check\`).
 */
import type { DecimalString } from '../decimal';

`;

const DECIMAL = ts.factory.createTypeReferenceNode('DecimalString');

/** Собрать текст schema.ts из контракта. */
export async function generate(contract = CONTRACT) {
  const ast = await openapiTS(pathToFileURL(contract), {
    alphabetize: false,
    exportType: true,
    transform(schema) {
      if (schema['x-ts-type'] === 'DecimalString') return DECIMAL;
      return undefined;
    },
  });
  return HEADER + astToString(ast);
}

async function main() {
  const check = process.argv.includes('--check');
  const outputs = [
    [OUTPUT, await generate(), 'contracts/openapi.yaml'],
    [AUDIT_OUTPUT, generateAuditEvents(), 'contracts/audit-events.yaml'],
  ];
  for (const [output, text, source] of outputs) {
    const where = relative(ROOT, output);
    if (check) {
      let current = '';
      try {
        current = readFileSync(output, 'utf8');
      } catch {
        // файла нет — значит, не совпадает
      }
      if (current !== text) {
        console.error(`${where} не совпадает с ${source}: выполните npm run api:gen`);
        process.exit(1);
      }
      console.log(`${where} актуален`);
      continue;
    }
    mkdirSync(dirname(output), { recursive: true });
    writeFileSync(output, text);
    console.log(`записан ${where}`);
  }
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? '').href) await main();
