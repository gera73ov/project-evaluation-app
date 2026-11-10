/**
 * FE-081 · строки дерева перерисовываются только при изменении своих данных (NFR-PERF-03, NFR-PERF-06).
 *
 * Объекты действий (ввод в ячейки, меню, статус ветки) создаются заново при каждой отрисовке
 * таблицы, и строка, которая не перерисовалась, держит прошлую копию. `useFresh` заменяет функции
 * такого объекта постоянными обёртками, которые вызывают функцию из последней отрисовки: обработчик
 * в неперерисованной строке не работает с устаревшим состоянием. Остальные поля копируются как есть.
 *
 * `sameSignature` — сравнение пропсов строки по «подписи»: плоскому списку всего, что строка
 * показывает. Объекты действий и контекст в сравнении не участвуют.
 */
import { useLayoutEffect, useState } from 'react';

type Fn = (...args: unknown[]) => unknown;

/** Значение последней отрисовки; меняется после фиксации (layout effect). */
class Latest<T> {
  constructor(private value: T) {}
  get(): T {
    return this.value;
  }
  set(value: T): void {
    this.value = value;
  }
}

export function useFresh<T extends object>(value: T | undefined): T | undefined {
  // не useRef: значение читают только обёртки при вызове, а не отрисовка
  const [latest] = useState(() => new Latest(value));
  useLayoutEffect(() => {
    latest.set(value);
  });
  const [wrappers] = useState(() => new Map<string, Fn>());
  if (!value) return undefined;
  const wrapper = (key: string): Fn => {
    const known = wrappers.get(key);
    if (known) return known;
    const fn: Fn = (...args) => {
      const current = latest.get();
      const target: unknown = current ? Reflect.get(current, key) : undefined;
      return typeof target === 'function' ? (target as Fn)(...args) : undefined;
    };
    wrappers.set(key, fn);
    return fn;
  };
  return Object.fromEntries(
    Object.entries(value).map(([key, v]) => [key, typeof v === 'function' ? wrapper(key) : v]),
  ) as T;
}

export function sameSignature(a: readonly unknown[], b: readonly unknown[]): boolean {
  return a.length === b.length && a.every((v, i) => Object.is(v, b.at(i)));
}
