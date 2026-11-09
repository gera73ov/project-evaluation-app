/**
 * FE-090 · данные сценариев: seed.py создаёт пользователей и печатает JSON с логинами.
 * Команда по умолчанию — из каталога backend через uv; на стенде её задаёт E2E_SEED_CMD
 * (например, `docker compose ... exec -T api python /e2e/seed.py`).
 */
import { execSync } from 'node:child_process';
import { writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

export const DATA_FILE = fileURLToPath(new URL('./.e2e-data.json', import.meta.url));

export default function globalSetup(): void {
  const backend = fileURLToPath(new URL('../backend', import.meta.url));
  const command = process.env.E2E_SEED_CMD ?? 'uv run --frozen python ../e2e/auth/seed.py';
  const output = execSync(command, { cwd: backend, encoding: 'utf8', stdio: ['ignore', 'pipe', 'inherit'] });
  const line = output.trim().split('\n').at(-1) ?? '';
  JSON.parse(line); // ошибка здесь — seed напечатал не JSON
  writeFileSync(DATA_FILE, line);
}
