/**
 * FE-064 · правила мастера первичной настройки (SPEC 7.1, FR-SA-02): пять шагов по порядку,
 * текущий — первый незавершённый (мастер продолжается с прерванного шага), значения шага —
 * поверх значений по умолчанию из contracts/settings.schema.json.
 */
import { useQuery } from '@tanstack/react-query';

import schema from '../../../../contracts/settings.schema.json';
import { api, type components } from '../../shared/api/client';
import { call } from '../../shared/api/problem';

export type SetupStep = components['schemas']['SetupStep'];
export type StepName = SetupStep['step'];

export const STEPS: readonly StepName[] = ['app', 'smtp', 'auth', 'security', 'first_admin'];

/** Ключи настроек каждого шага: шаг 3 в режиме «Приложение» — ещё и политика паролей (7.1). */
export const STEP_KEYS = new Map<StepName, readonly string[]>([
  ['app', ['app.base_url', 'app.timezone']],
  ['smtp', ['smtp.server', 'smtp.password']],
  [
    'auth',
    [
      'auth.mode',
      'auth.ad.connection',
      'auth.ad.bind_password',
      'auth.ad.access_groups',
      'auth.ad.role_mapping',
      'security.password_policy',
    ],
  ],
  [
    'security',
    ['security.session', 'security.lockout', 'security.mfa_policy', 'security.admin_networks', 'security.alert_email'],
  ],
  ['first_admin', []],
]);

type Prop = { default?: unknown };
const PROPS = new Map(Object.entries((schema as { properties: Record<string, Prop> }).properties));

/** Значения шага поверх значений по умолчанию: форма не ломается на пропущенном ключе. */
export function withDefaults(step: StepName, values: object | undefined): Record<string, unknown> {
  const given = new Map(Object.entries(values ?? {}));
  return Object.fromEntries(
    (STEP_KEYS.get(step) ?? []).map((key) => [key, given.get(key) ?? PROPS.get(key)?.default ?? null]),
  );
}

/** Первый незавершённый шаг; null — мастер пройден. */
export function currentStep(steps: readonly SetupStep[]): StepName | null {
  return STEPS.find((name) => !steps.find((s) => s.step === name)?.done) ?? null;
}

/** Открыть можно пройденный шаг и текущий, будущие — нет. */
export function reachable(name: StepName, steps: readonly SetupStep[]): boolean {
  const current = currentStep(steps);
  return current === null || STEPS.indexOf(name) <= STEPS.indexOf(current);
}

export const isHttpsUrl = (s: string) => {
  if (!/^https:\/\//.test(s) || s.length > 2048) return false;
  try {
    return Boolean(new URL(s).host);
  } catch {
    return false;
  }
};

/** Часовые пояса IANA из браузера; запасной список — если `supportedValuesOf` нет. */
export function timezones(): string[] {
  const intl = Intl as { supportedValuesOf?: (key: string) => string[] };
  const list = intl.supportedValuesOf?.('timeZone') ?? [];
  const base = [
    'Europe/Kaliningrad',
    'Europe/Moscow',
    'Europe/Samara',
    'Asia/Yekaterinburg',
    'Asia/Novosibirsk',
    'UTC',
  ];
  return [...new Set([...base, ...list])].sort();
}

export const setupKey = ['system', 'setup'] as const;

export function useSetup() {
  return useQuery({
    queryKey: setupKey,
    queryFn: () =>
      Promise.all(STEPS.map((step) => call(() => api.GET('/system/setup/{step}', { params: { path: { step } } })))),
    retry: false,
  });
}
