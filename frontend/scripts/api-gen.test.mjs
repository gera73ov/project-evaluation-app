import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { OUTPUT, generate } from './api-gen.mjs';

describe('api-gen (API-006)', () => {
  it('сгенерированные типы совпадают с contracts/openapi.yaml', async () => {
    expect(readFileSync(OUTPUT, 'utf8')).toBe(await generate());
  }, 30_000);

  it('десятичные схемы контракта становятся DecimalString', async () => {
    const text = await generate();
    expect(text).toContain("import type { DecimalString } from '../decimal';");
    expect(text).toMatch(/HoursString: DecimalString;/);
    expect(text).toMatch(/MoneyString: DecimalString;/);
  }, 30_000);
});
