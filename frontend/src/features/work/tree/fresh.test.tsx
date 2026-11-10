/**
 * FE-081 · постоянные обёртки действий и сравнение строк по подписи.
 */
import { renderHook } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { sameSignature, useFresh } from './fresh';

describe('useFresh', () => {
  it('функции — постоянные обёртки, которые зовут версию последней отрисовки', () => {
    const { result, rerender } = renderHook(({ n }) => useFresh({ n, get: () => n }), { initialProps: { n: 1 } });
    const first = result.current;
    expect(first?.get()).toBe(1);
    rerender({ n: 2 });
    expect(result.current?.get).toBe(first?.get);
    // устаревшая копия объекта в неперерисованной строке видит новое состояние
    expect(first?.get()).toBe(2);
    expect(result.current?.n).toBe(2);
  });

  it('без объекта — undefined', () => {
    const { result } = renderHook(() => useFresh<{ f: () => void }>(undefined));
    expect(result.current).toBeUndefined();
  });
});

describe('sameSignature', () => {
  it('сравнивает поэлементно по Object.is', () => {
    const o = {};
    expect(sameSignature([1, 'a', o, null], [1, 'a', o, null])).toBe(true);
    expect(sameSignature([o], [{}])).toBe(false);
    expect(sameSignature([1], [1, 2])).toBe(false);
  });
});
