/**
 * API-006 · генерация TS-типов из contracts/openapi.yaml (SPEC 15.1, 13.1).
 *
 *   npm run api:gen         — записать src/shared/api/generated/schema.ts
 *   npm run api:gen:check   — проверить, что файл совпадает с контрактом (CI)
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

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
export const CONTRACT = join(ROOT, '..', 'contracts', 'openapi.yaml');
export const OUTPUT = join(ROOT, 'src', 'shared', 'api', 'generated', 'schema.ts');

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
  const text = await generate();
  const where = relative(ROOT, OUTPUT);
  if (check) {
    let current = '';
    try {
      current = readFileSync(OUTPUT, 'utf8');
    } catch {
      // файла нет — значит, не совпадает
    }
    if (current !== text) {
      console.error(`${where} не совпадает с contracts/openapi.yaml: выполните npm run api:gen`);
      process.exit(1);
    }
    console.log(`${where} актуален`);
    return;
  }
  mkdirSync(dirname(OUTPUT), { recursive: true });
  writeFileSync(OUTPUT, text);
  console.log(`записан ${where}`);
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? '').href) await main();
