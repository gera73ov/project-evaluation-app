/**
 * FE-090 · данные сценариев: seed.py создаёт пользователей и печатает JSON с логинами.
 * Команды по умолчанию — из каталога backend через uv; на стенде их задают E2E_SEED_CMD
 * (например, `docker compose ... exec -T api python /e2e/auth/seed.py`) и E2E_WORK_SEED_CMD
 * (FE-091: модератор с TOTP и два эксперта для сценариев рабочего экрана), E2E_ADMIN_SEED_CMD
 * (FE-094: администратор, два модератора и пользователь для сценариев админки), E2E_PERF_SEED_CMD
 * (FE-081: модератор для замеров рабочего экрана), E2E_STATS_SEED_CMD (FE-093: модератор и руководитель
 * пресейла для статистики, снимков и портфеля).
 */
import { execSync } from 'node:child_process';
import { writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

export const DATA_FILE = fileURLToPath(new URL('./.e2e-data.json', import.meta.url));
export const WORK_DATA_FILE = fileURLToPath(new URL('./.e2e-work-data.json', import.meta.url));
export const ADMIN_DATA_FILE = fileURLToPath(new URL('./.e2e-admin-data.json', import.meta.url));
export const STATS_DATA_FILE = fileURLToPath(new URL('./.e2e-stats-data.json', import.meta.url));
export const PERF_DATA_FILE = fileURLToPath(new URL('./.e2e-perf-data.json', import.meta.url));

/** Команда из каталога backend; последняя строка вывода — JSON. */
export function runJson(command: string): string {
  const backend = fileURLToPath(new URL('../backend', import.meta.url));
  const output = execSync(command, { cwd: backend, encoding: 'utf8', stdio: ['ignore', 'pipe', 'inherit'] });
  const line = output.trim().split('\n').at(-1) ?? '';
  JSON.parse(line); // ошибка здесь — команда напечатала не JSON
  return line;
}

function runSeed(command: string, file: string): void {
  writeFileSync(file, runJson(command));
}

export default function globalSetup(): void {
  runSeed(process.env.E2E_SEED_CMD ?? 'uv run --frozen python ../e2e/auth/seed.py', DATA_FILE);
  runSeed(process.env.E2E_WORK_SEED_CMD ?? 'uv run --frozen python ../e2e/work/seed.py', WORK_DATA_FILE);
  runSeed(process.env.E2E_ADMIN_SEED_CMD ?? 'uv run --frozen python ../e2e/admin/seed.py', ADMIN_DATA_FILE);
  runSeed(process.env.E2E_STATS_SEED_CMD ?? 'uv run --frozen python ../e2e/stats/seed.py', STATS_DATA_FILE);
  if (process.env.E2E_PERF)
    runSeed(process.env.E2E_PERF_SEED_CMD ?? 'uv run --frozen python ../e2e/perf/seed.py', PERF_DATA_FILE);
}
