/**
 * FE-005 · режим входа до входа (11.1 №3–5): «ad» — учётная запись компании, подсказка AD, нет
 * «Забыли пароль?»; «app» — учётная запись приложения.
 *
 * Режим отдаёт публичный `GET /auth/options` (CR-001). Если он недоступен, экран начинает с
 * «app», а после LOGIN_FAILED режим уточняется по расширению `auth_mode` в ответе сервера.
 */
import { api } from '../../shared/api/client';

export type AuthMode = 'app' | 'ad';

function isMode(value: unknown): value is AuthMode {
  return value === 'app' || value === 'ad';
}

export async function loadAuthMode(): Promise<AuthMode> {
  try {
    const { data } = await api.GET('/auth/options');
    if (isMode(data?.auth_mode)) return data.auth_mode;
  } catch {
    // нет сети — остаётся режим по умолчанию
  }
  return 'app';
}

export { isMode as isAuthMode };
