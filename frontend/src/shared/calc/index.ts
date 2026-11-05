/**
 * FE-002 · клиентский расчётный модуль (SPEC раздел 6) на decimal.js — зеркало серверного
 * `backend/src/estimator/domain/calc`. Обе реализации проверяются одними фикстурами
 * `contracts/fixtures/calc`. Клиент считает для мгновенного отображения; для экспорта, снимков и
 * проверки источник правды — сервер.
 */
export * from './analytics';
export * from './decimal';
export * from './leaf';
export * from './model';
export * from './money';
export * from './project';
export * from './tree';
