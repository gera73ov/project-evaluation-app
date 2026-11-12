/**
 * FE-081, QA-020 · производительность рабочего экрана на настоящем API (NFR-PERF-02, NFR-PERF-03,
 * NFR-PERF-06, FR-TREE-15). Модератор создаёт два проекта с двумя фазами и двумя дисциплинами,
 * `fill.py` доводит их до 2 000 и 5 000 узлов. Замеры:
 * - открытие экрана до интерактивности (дерево и первая строка с ячейкой O), p95 —
 *   ≤ 2 с на 2 000 узлах и ≤ 4 с на 5 000;
 * - ввод O → пересчёт суммы листа и итога ветки на экране — ≤ 100 мс;
 * - прокрутка всего дерева на 5 000 узлах — кадры не реже 30 fps; в DOM не больше ~150 строк.
 *
 * Пороги SPEC заданы для ноутбука Core i5 / 8 ГБ и сети 100 Мбит. QA-020 приближает такую машину
 * на стенде через DevTools: E2E_PERF_CPU — во сколько раз замедлить CPU страницы, E2E_PERF_NET —
 * пропускная способность сети в Мбит/с; E2E_PERF_RUNS — число открытий для p95 (по умолчанию 3).
 * Цифры прогона (и оценка скорости CPU страницы, `cpuBenchMs`) пишутся в отчёт
 * (`perf-report.json` во вложениях теста).
 */
import { readFileSync, writeFileSync } from 'node:fs';
import { expect, test, type Page } from '@playwright/test';

import { PERF_DATA_FILE, runJson } from '../global-setup';
import { currentStep, totp } from '../auth/totp';
import { spendLogin } from '../auth/budget';

interface Seed {
  moderator: { id: string; login: string; name: string };
  phases: string[];
  disciplines: string[];
  password: string;
  totp: string;
}

const seed = JSON.parse(readFileSync(PERF_DATA_FILE, 'utf8')) as Seed;
/** Размер проекта → порог открытия до интерактивности, мс (NFR-PERF-02). */
const SIZES = { 2000: 2000, 5000: 4000 } as const;
const NODES = 5000;
const RUNS = Number(process.env.E2E_PERF_RUNS ?? 3);
const CPU = Number(process.env.E2E_PERF_CPU ?? 1);
const NET = Number(process.env.E2E_PERF_NET ?? 0);
const FILL = process.env.E2E_PERF_FILL_CMD ?? 'uv run --frozen python ../e2e/perf/fill.py';

test.describe.configure({ mode: 'serial' });

let page: Page;
const projects: Record<number, string> = {};
const report: Record<string, unknown> = { cpuThrottle: CPU, netMbit: NET || null, runs: RUNS };

/** p95 по методу ближайшего ранга: на 20 прогонах — 19-й по возрастанию. */
function p95(values: number[]): number {
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.max(0, Math.ceil(sorted.length * 0.95) - 1)];
}

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
  await spendLogin();
  await page.getByRole('button', { name: 'Войти' }).click();
  const step = currentStep();
  await page.getByLabel('Цифра 1').pressSequentially(totp(seed.totp, step));
  await expect(page).not.toHaveURL(/\/login/);

  const nodesInProject: Record<number, number> = {};
  for (const size of Object.keys(SIZES).map(Number)) {
    const { project } = await api<{ project: { id: string } }>('POST', '/projects', {
      name: `E2E замеры ${size} ${Date.now()}`,
      customer: 'ООО «Замеры»',
      phase_ids: seed.phases,
    });
    projects[size] = project.id;
    for (const id of seed.disciplines) await api('POST', `/projects/${project.id}/disciplines`, { discipline_id: id });
    const filled = JSON.parse(runJson(`${FILL} ${project.id} ${size}`)) as { nodes: number };
    nodesInProject[size] = filled.nodes;
    expect(filled.nodes).toBeGreaterThan(size - 20);
  }
  report.nodesInProject = nodesInProject;

  // QA-020: приближение к эталонному ноутбуку — замедление CPU и сеть заданной ширины (Chromium)
  const cdp = await context.newCDPSession(page);
  if (CPU > 1) await cdp.send('Emulation.setCPUThrottlingRate', { rate: CPU });
  if (NET > 0) {
    const bytes = (NET * 1_000_000) / 8;
    await cdp.send('Network.enable');
    await cdp.send('Network.emulateNetworkConditions', {
      offline: false,
      latency: 2,
      downloadThroughput: bytes,
      uploadThroughput: bytes,
    });
  }
  // скорость CPU страницы с учётом замедления: один и тот же расчёт, медиана пяти замеров
  report.cpuBenchMs = await page.evaluate(() => {
    const times: number[] = [];
    for (let r = 0; r < 5; r += 1) {
      const start = performance.now();
      let acc = 0;
      for (let i = 0; i < 2_000_000; i += 1) acc += Math.sqrt(i) % 7;
      times.push(performance.now() - start + (acc < 0 ? 1 : 0));
    }
    return Math.round(times.sort((a, b) => a - b)[2]);
  });
});

test.afterAll(async ({}, info) => {
  await info.attach('perf-report.json', { body: JSON.stringify(report, null, 2), contentType: 'application/json' });
  console.log('QA-020', JSON.stringify(report));
  await page.context().close();
});

for (const [size, limit] of Object.entries(SIZES).map(([n, ms]) => [Number(n), ms] as const)) {
  test(`открытие экрана на ${size} узлах — до интерактивности p95 не больше ${limit / 1000} с (NFR-PERF-02)`, async () => {
    test.setTimeout(60_000 + RUNS * 15_000);
    const runs: number[] = [];
    for (let i = 0; i < RUNS; i += 1) {
      await page.goto('/');
      const started = Date.now();
      await page.goto(`/projects/${projects[size]}`);
      await expect(firstLeaf()).toBeVisible({ timeout: 15_000 });
      runs.push(Date.now() - started);
    }
    report[`open${size}`] = { ms: runs, p95: p95(runs) };
    const rows = await tree().locator('[role="row"]').count();
    report[`domRows${size}`] = rows;
    expect(rows).toBeLessThanOrEqual(160);
    expect(p95(runs)).toBeLessThanOrEqual(limit);
  });
}

/**
 * E2E_PERF_PROFILE=1 — профиль CPU на время замера во вложениях (`<name>.cpuprofile`, открывается в
 * DevTools → Performance). Возвращает функцию, которая останавливает профиль и прикладывает его.
 */
async function profile(name: string): Promise<() => Promise<void>> {
  if (!process.env.E2E_PERF_PROFILE) return async () => {};
  const cdp = await page.context().newCDPSession(page);
  await cdp.send('Profiler.enable');
  await cdp.send('Profiler.setSamplingInterval', { interval: 100 });
  await cdp.send('Profiler.start');
  return async () => {
    const { profile: data } = await cdp.send('Profiler.stop');
    const file = test.info().outputPath(`${name}.cpuprofile`);
    writeFileSync(file, JSON.stringify(data));
    await test.info().attach(`${name}.cpuprofile`, { path: file, contentType: 'application/json' });
  };
}

test('ввод O пересчитывает сумму листа и итог ветки за 100 мс (NFR-PERF-03)', async () => {
  // экран проекта на 5 000 узлах открыт последним замером открытия
  await expect(page).toHaveURL(new RegExp(projects[NODES]));
  const leaf = firstLeaf();
  const runs: number[] = [];
  const stop = await profile('input');
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
  await stop();
  report.inputMs = runs;
  expect(Math.max(...runs)).toBeLessThanOrEqual(100);
});

test('прокрутка всего дерева — не ниже 30 fps, в DOM не больше ~150 строк (NFR-PERF-06, FR-TREE-15)', async () => {
  const scroll = tree().locator('.tree-scroll');
  const stop = await profile('scroll');
  const stats = await scroll.evaluate(
    (el) =>
      new Promise<{ frames: number; seconds: number; worstMs: number; p95Ms: number; slow: number; maxRows: number }>(
        (resolve) => {
          const frames: number[] = [];
          let maxRows = 0;
          let last = performance.now();
          const first = last;
          const step = () => {
            const now = performance.now();
            frames.push(now - last);
            last = now;
            // подсчёт строк — каждый 10-й кадр: сам обход DOM заметно ест кадр при замедленном CPU
            if (frames.length % 10 === 0) maxRows = Math.max(maxRows, el.querySelectorAll('[role="row"]').length);
            if (el.scrollTop + el.clientHeight >= el.scrollHeight - 1) {
              const sorted = [...frames].sort((a, b) => a - b);
              resolve({
                frames: frames.length,
                seconds: (now - first) / 1000,
                worstMs: Math.max(...frames),
                p95Ms: sorted[Math.ceil(sorted.length * 0.95) - 1],
                slow: frames.filter((f) => f > 1000 / 30).length,
                maxRows,
              });
              return;
            }
            el.scrollTop += 120;
            requestAnimationFrame(step);
          };
          requestAnimationFrame(step);
        },
      ),
  );
  await stop();
  const fps = stats.frames / stats.seconds;
  report.scroll = {
    ...stats,
    fps: Math.round(fps),
    worstMs: Math.round(stats.worstMs),
    p95Ms: Math.round(stats.p95Ms),
    slowShare: Math.round((stats.slow / stats.frames) * 1000) / 10,
  };
  expect(stats.maxRows).toBeLessThanOrEqual(160);
  expect(fps).toBeGreaterThanOrEqual(30);
  // FE-081: на машине без замедления долгие кадры — только исключение, не больше 1%. При
  // замедлении CPU (QA-020) норма SPEC — средние 30 fps, доля долгих кадров идёт в отчёт.
  if (CPU <= 1) expect(stats.slow).toBeLessThanOrEqual(Math.ceil(stats.frames / 100));
});
