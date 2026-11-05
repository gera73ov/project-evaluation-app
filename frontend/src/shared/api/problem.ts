/**
 * FE-003 · ошибки API в формате Problem Details (RFC 9457, api-conventions 5,
 * contracts/errors.yaml). Пользователю показывается текст по коду из i18n (`errors.<CODE>`),
 * а у 5xx — ещё и `error_id`, который пользователь сообщает администратору.
 */
import i18n from '../i18n';

export interface Problem {
  type: string;
  title: string;
  status: number;
  code: string;
  error_id: string;
  detail?: string;
  [extension: string]: unknown;
}

export class ApiError extends Error {
  override name = 'ApiError';

  constructor(
    readonly status: number,
    readonly problem: Problem,
    readonly retryAfter: string | null = null,
  ) {
    super(problem.title);
  }

  get code(): string {
    return this.problem.code;
  }

  get errorId(): string {
    return this.problem.error_id;
  }

  /** Расширение Problem по имени (`auth_mode`, `locked_by_name`, …). */
  extension(name: string): unknown {
    return Object.entries(this.problem).find(([key]) => key === name)?.[1];
  }
}

export function isProblem(body: unknown): body is Problem {
  return (
    typeof body === 'object' &&
    body !== null &&
    typeof (body as Problem).code === 'string' &&
    typeof (body as Problem).status === 'number'
  );
}

/** Ошибка без тела Problem (сеть, прокси, неожиданный ответ). */
export function networkProblem(status = 0): Problem {
  return {
    type: 'about:blank',
    title: 'Network error',
    status,
    code: status === 0 ? 'NETWORK' : 'UNKNOWN',
    error_id: '',
  };
}

/**
 * Результат openapi-fetch → данные или ApiError. `response` нужен ради статуса и Retry-After.
 */
export function unwrap<T>(result: { data?: T; error?: unknown; response: Response }): T {
  if (result.response.ok) return result.data as T;
  const problem = isProblem(result.error) ? result.error : networkProblem(result.response.status);
  throw new ApiError(result.response.status, problem, result.response.headers.get('Retry-After'));
}

/** Запрос openapi-fetch с переводом сетевого сбоя в ApiError(NETWORK). */
export async function call<T>(
  request: () => Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  let result;
  try {
    result = await request();
  } catch {
    throw new ApiError(0, networkProblem());
  }
  return unwrap(result);
}

/** Текст ошибки для пользователя (errors.yaml `user_message`, дословно). */
export function errorMessage(error: unknown, variant?: 'ad' | undefined): string {
  if (!(error instanceof ApiError)) return i18n.t('errors.UNKNOWN', { error_id: '—' });
  const params = { ...error.problem, error_id: error.errorId || '—' };
  const keys = [variant ? `errors.${error.code}_${variant}` : null, `errors.${error.code}`];
  for (const key of keys) {
    if (key && i18n.exists(key)) return i18n.t(key, params);
  }
  return error.status >= 500
    ? i18n.t('errors.INTERNAL_ERROR', params)
    : i18n.t('errors.UNKNOWN', params);
}

/** Показывать ли `error_id` рядом с текстом (5xx, FR-UI-05). */
export function showsErrorId(error: unknown): boolean {
  return error instanceof ApiError && error.status >= 500 && error.errorId !== '';
}
