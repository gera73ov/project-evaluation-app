import Decimal from 'decimal.js';
import { describe, expect, it } from 'vitest';
import type { components } from './client';
import { asDecimalString, toDecimalString, type DecimalString } from './decimal';

type Hours = components['schemas']['HoursString'];
type Money = components['schemas']['MoneyString'];

describe('DecimalString', () => {
  it('принимает строки формата API', () => {
    for (const value of ['0', '12.5', '-3.45', '1146798', '92.5']) {
      expect(asDecimalString(value)).toBe(value);
    }
  });

  it('отклоняет запятую, экспоненту и пустую строку', () => {
    for (const value of ['12,5', '1e3', '', '.5', '5.', ' 1']) {
      expect(() => asDecimalString(value)).toThrow(RangeError);
    }
  });

  it('переводит Decimal без экспоненты и без потери точности', () => {
    expect(toDecimalString(new Decimal('1e21'))).toBe('1000000000000000000000');
    expect(toDecimalString(new Decimal(115).div(6).toDecimalPlaces(2))).toBe('19.17');
  });

  it('сгенерированные часы и деньги — branded-тип, а не string', () => {
    const hours: Hours = asDecimalString('8');
    const money: Money = hours;
    const same: DecimalString = money;
    // @ts-expect-error обычная строка не подходит туда, где API ждёт десятичное значение
    const wrong: Hours = '8';
    expect([hours, money, same, wrong]).toHaveLength(4);
  });
});
