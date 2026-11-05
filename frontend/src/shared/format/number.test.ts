import { describe, expect, it } from 'vitest';

import { dec } from '../calc/decimal';
import {
  DASH,
  MINUS,
  NBSP,
  formatFork,
  formatHours,
  formatHoursInput,
  formatMoney,
  formatNumber,
  formatPercent,
  formatRate,
} from './number';

describe('форматирование чисел (DESIGN.md 11)', () => {
  it('часы — 1 знак, тысячи через неразрывный пробел, ROUND_HALF_UP', () => {
    expect(formatHours(dec('406.51'))).toBe('406,5');
    expect(formatHours('1240.45')).toBe(`1${NBSP}240,5`);
    expect(formatHours(dec('425.5442'), { unit: true })).toBe(`425,5${NBSP}ч`);
    expect(formatHours(dec('3.45'))).toBe('3,5');
    expect(formatHours(null)).toBe(DASH);
  });

  it('деньги — целые, большие значения без потери точности', () => {
    expect(formatMoney('1146798')).toBe(`1${NBSP}146${NBSP}798${NBSP}₽`);
    expect(formatMoney(dec('12977.5'), 'USD')).toBe(`12${NBSP}978${NBSP}USD`);
    expect(formatMoney('10999945000000000')).toBe(
      ['10', '999', '945', '000', '000', '000'].join(NBSP) + `${NBSP}₽`,
    );
    expect(formatMoney(null)).toBe(DASH);
  });

  it('проценты, курс, знак', () => {
    expect(formatPercent(dec('24.1228'))).toBe('24%');
    expect(formatPercent('12.5', 1)).toBe('12,5%');
    expect(formatPercent(null)).toBe(DASH);
    expect(formatRate('92.5')).toBe('92,5000');
    expect(formatNumber('-4.66', 1)).toBe(`${MINUS}4,7`);
    expect(formatNumber('28.3', 1, { sign: true })).toBe('+28,3');
    expect(formatNumber('-0.04', 1)).toBe('0,0');
    expect(formatNumber('999.96', 1)).toBe(`1${NBSP}000,0`);
  });

  it('ввод и вилка O–R–P', () => {
    expect(formatHoursInput('12.0')).toBe('12');
    expect(formatHoursInput(dec('12.5'))).toBe('12,5');
    expect(formatHoursInput(null)).toBe('');
    expect(formatFork('40', '60', '100')).toBe('40–60–100');
    expect(formatFork('0.5', null, '2')).toBe(`0,5–${DASH}–2`);
  });
});
