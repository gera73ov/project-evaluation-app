/**
 * FE-081 · производительность рабочего экрана на настоящем API (NFR-PERF-02, NFR-PERF-03,
 * NFR-PERF-06, FR-TREE-15). Модератор создаёт проект с двумя фазами и двумя дисциплинами,
 * `fill.py` доводит его до 5 000 узлов. Замеры:
 * - открытие экрана до интерактивности (дерево и первая строка с ячейкой O) — ≤ 4 с;
 * - ввод O → пересчёт суммы листа и итога ветки на экране — ≤ 100 мс;
 * - прокрутка всего дерева — кадры не реже 30 fps; в DOM не больше ~150 строк.
 *
 * Пороги SPEC заданы для ноутбука Core i5 / 8 ГБ. Цифры каждого прогона пишутся в отчёт
 * (`perf-report.json` во вложениях теста) — по ним сверяется QA-020.
 */
import { readFileSync, writeFileSync } from 'node:fs';
import { expect, test, type Page } from '@playwright/test';

import { PERF_DATA_FILE, runJson } from '../global-setup';
import { currentStep, totp } from '../auth/totp';

interface Seed {
  moderator: { id: string; login: string; name: string };
  phases: string[];
  disciplines: string[];
  password: string;
  totp: string;
}

const seed = JSON.parse(readFileSync(PERF_DATA_FILE, 'utf8')) as Seed;
const NODES = 5000;
const FILL = process.env.E2E_PERF_FILL_CMD ?? 'uv run --frozen python ../e2e/perf/fill.py';

test.describe.configure({ mode: 'serial' });

let page: Page;
let projectId = '';
const report: Record<string, unknown> = { nodes: NODES };

async function api<T>(method: string, path: string, data?: unknown): Promise<T> {
  const csrf = (await page.context().cookies()).find((c) => c.name === '__Host-csrf')?.value ?? '';
  const response = await page.request.fetch(`/api/v1${path}`, { method, data, headers: { 'X-CSRF-Token': csrf } });
  const text = await response.text();
  expect(response.ok(), `${method} ${path}: ${text}`).toBe(true);
  return (text ? JSON.parse(text) : null) as T;
}

const tree = () => page.getByRole('treegrid', { name: 'Дерево оценки' });
/** Первый лист первой ветки: наполнение `fill.py` даёт ему это название. */
const LEAF = 'Задача Модуль 1.1.1';
const firstLeaf = () => tree().locator('.vrow [role="row"]').filter({ hasText: LEAF }).first();

test.beforeAll(async ({ browser }) => {
  test.setTimeout(120_000);
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  page = await context.newPage();
  await page.goto('/login');
  await page.getByLabel('Логин').fill(seed.moderator.login);
  await page.getByLabel('Пароль').fill(seed.password);
  await page.getByRole('button', { name: 'Войти' }).click();
  const step = currentStep();
  await page.getByLabel('Цифра 1').pressSequentially(totp(seed.totp, step));
  await expect(page).not.toHaveURL(/\/login/);

  const { project } = await api<{ project: { id: string } }>('POST', '/projects', {
    name: `E2E замеры ${Date.now()}`,
    customer: 'ООО «Замеры»',
    phase_ids: seed.phases,
  });
  projectId = project.id;
  for (const id of seed.disciplines) await api('POST', `/projects/${projectId}/disciplines`, { discipline_id: id });
  const filled = JSON.parse(runJson(`${FILL} ${projectId} ${NODES}`)) as { nodes: number };
  report.nodesInProject = filled.nodes;
  expect(filled.nodes).toBeGreaterThan(NODES - 20);
});

test.afterAll(async ({}, info) => {
  await info.attach('perf-report.json', { body: JSON.stringify(report, null, 2), contentType: 'application/json' });
  console.log('FE-081', JSON.stringify(report));
  await page.context().close();
});

test('открытие экрана на 5 000 узлах — до интерактивности не больше 4 с (NFR-PERF-02)', async () => {
  const runs: number[] = [];
  for (let i = 0; i < 3; i += 1) {
    await page.goto('/');
    const started = Date.now();
    await page.goto(`/projects/${projectId}`);
    await expect(firstLeaf()).toBeVisible({ timeout: 15_000 });
    runs.push(Date.now() - started);
  }
  report.openMs = runs;
  const rows = await tree().locator('[role="row"]').count();
  report.domRows = rows;
  expect(rows).toBeLessThanOrEqual(160);
  expect(Math.max(...runs)).toBeLessThanOrEqual(4000);
});

test('ввод O пересчитывает сумму листа и итог ветки за 100 мс (NFR-PERF-03)', async () => {
  const leaf = firstLeaf();
  const runs: number[] = [];
  // E2E_PERF_PROFILE=1 — профиль CPU на время ввода во вложениях (открывается в DevTools → Performance)
  const cdp = process.env.E2E_PERF_PROFILE ? await page.context().newCDPSession(page) : null;
  if (cdp) {
    await cdp.send('Profiler.enable');
    await cdp.send('Profiler.setSamplingInterval', { interval: 100 });
    await cdp.send('Profiler.start');
  }
  for (let i = 0; i < 5; i += 1) {
    await leaf.getByRole('button', { name: /^O:/ }).click();
    const input = leaf.getByRole('textbox', { name: 'O' });
    await input.fill(String(3 + (i % 2)));
    // от нажатия Enter до смены суммы листа в DOM: обработчик и наблюдатель — в странице
    const ms = await input.evaluate(
      (el) =>
        new Promise<number>((resolve) => {
          const row = el.closest('[role="row"]');
          const sum = row?.querySelector('.td.e');
          const before = sum?.textContent ?? '';
          let start = 0;
          const observer = new MutationObserver(() => {
            if (start && sum?.textContent !== before) {
              observer.disconnect();
              resolve(performance.now() - start);
            }
          });
          observer.observe(row ?? document.body, { subtree: true, childList: true, characterData: true });
          start = performance.now();
          el.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
          setTimeout(() => resolve(Number.POSITIVE_INFINITY), 5000);
        }),
    );
    runs.push(Math.round(ms * 10) / 10);
    await expect(leaf.getByRole('button', { name: `O: ${3 + (i % 2)}` })).toBeVisible();
  }
  if (cdp) {
    const { profile } = await cdp.send('Profiler.stop');
    const file = test.info().outputPath('input.cpuprofile');
    writeFileSync(file, JSON.stringify(profile));
    await test.info().attach('input.cpuprofile', { path: file, contentType: 'application/json' });
  }
  report.inputMs = runs;
  expect(Math.max(...runs)).toBeLessThanOrEqual(100);
});

test('прокрутка всего дерева — не ниже 30 fps, в DOM не больше ~150 строк (NFR-PERF-06, FR-TREE-15)', async () => {
  const scroll = tree().locator('.tree-scroll');
  const stats = await scroll.evaluate(
    (el) =>
      new Promise<{ frames: number; seconds: number; worstMs: number; slow: number; maxRows: number }>((resolve) => {
        const frames: number[] = [];
        let maxRows = 0;
        let last = performance.now();
        const first = last;
        const step = () => {
          const now = performance.now();
          frames.push(now - last);
          last = now;
          maxRows = Math.max(maxRows, el.querySelectorAll('[role="row"]').length);
          if (el.scrollTop + el.clientHeight >= el.scrollHeight - 1) {
            resolve({
              frames: frames.length,
              seconds: (now - first) / 1000,
              worstMs: Math.max(...frames),
              slow: frames.filter((f) => f > 1000 / 30).length,
              maxRows,
            });
            return;
          }
          el.scrollTop += 120;
          requestAnimationFrame(step);
        };
        requestAnimationFrame(step);
      }),
  );
  const fps = stats.frames / stats.seconds;
  report.scroll = { ...stats, fps: Math.round(fps), worstMs: Math.round(stats.worstMs) };
  expect(stats.maxRows).toBeLessThanOrEqual(160);
  expect(fps).toBeGreaterThanOrEqual(30);
  // отдельные долгие кадры допустимы только как исключение: не больше 1% кадров
  expect(stats.slow).toBeLessThanOrEqual(Math.ceil(stats.frames / 100));
});
