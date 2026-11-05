/**
 * FE-005 · режим входа до входа (11.1 №3–5): «ad» — учётная запись компании, подсказка AD, нет
 * «Забыли пароль?»; «app» — учётная запись приложения.
 *
 * Контракт 1.0 отдаёт режим только в `GET /me` и в расширении `auth_mode` ошибки LOGIN_FAILED.
 * До решения владельца продукта (вопрос в треде, CR) источники по порядку:
 * `<meta name="auth-mode">` → `GET /auth/options` (если появится) → «app»; после LOGIN_FAILED
 * режим уточняется по ответу сервера.
 */
import { API_BASE } from '../../shared/api/client';

export type AuthMode = 'app' | 'ad';

function isMode(value: unknown): value is AuthMode {
  return value === 'app' || value === 'ad';
}

export function authModeFromMeta(doc: Document = document): AuthMode | null {
  const value = doc.querySelector<HTMLMetaElement>('meta[name="auth-mode"]')?.content;
  return isMode(value) ? value : null;
}

export async function loadAuthMode(fetcher: typeof fetch = fetch): Promise<AuthMode> {
  const meta = authModeFromMeta();
  if (meta) return meta;
  try {
    const response = await fetcher(`${window.location.origin}${API_BASE}/auth/options`, { credentials: 'same-origin' });
    if (response.ok) {
      const body: unknown = await response.json();
      const mode = (body as { auth_mode?: unknown }).auth_mode;
      if (isMode(mode)) return mode;
    }
  } catch {
    // нет эндпоинта или сети — остаётся режим по умолчанию
  }
  return 'app';
}

export { isMode as isAuthMode };
