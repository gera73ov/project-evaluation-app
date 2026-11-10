/**
 * FE-061 · правила экрана «Аутентификация» (SPEC 11.2 №2–6, FR-AUTH-AD-01…07): форма AD из
 * значений раздела `auth` (ключи settings.schema.json), разбор «host:port», проверка полей,
 * подпись параметров — проверки «подключение» и «вход» действуют, пока она не изменилась.
 */
export type Protocol = 'ldaps' | 'starttls';
export type MappedRole = 'moderator' | 'presale';

export type Connection = {
  controllers: { host: string; port: number }[];
  protocol: Protocol;
  ca_cert_pem: string | null;
  base_dn: string | null;
  user_filter: string;
  login_attribute: 'sAMAccountName' | 'userPrincipalName';
  attr_full_name: string;
  attr_email: string;
  attr_department: string;
  bind_dn: string | null;
  timeout_seconds: number;
};

export type RoleMapping = { enabled: boolean; mappings: { group_dn: string; role: MappedRole }[] };

/** Форма: контроллеры и группы — строками, как их вводит человек. */
export type AuthForm = {
  controllers: string[];
  protocol: Protocol;
  caCert: string | null;
  baseDn: string;
  userFilter: string;
  loginAttribute: Connection['login_attribute'];
  attrFullName: string;
  attrEmail: string;
  attrDepartment: string;
  bindDn: string;
  timeout: number;
  /** Новый пароль сервисной учётки; null — не менять («••••••, изменить»). */
  bindPassword: string | null;
  passwordSet: boolean;
  accessGroups: string[];
  mappingEnabled: boolean;
  moderatorGroup: string;
  presaleGroup: string;
  /** Прочие строки сопоставления (если на сервере их больше одной на роль) — сохраняются как есть. */
  extraMappings: RoleMapping['mappings'];
};

export const DEFAULT_PORT: Record<Protocol, number> = { ldaps: 636, starttls: 389 };
export const MAX_CONTROLLERS = 10;
export const MAX_GROUPS = 50;
export const CA_MAX_BYTES = 64 * 1024;

const DEFAULT_CONNECTION: Connection = {
  controllers: [],
  protocol: 'ldaps',
  ca_cert_pem: null,
  base_dn: null,
  user_filter: '(&(objectClass=user)(sAMAccountName={login}))',
  login_attribute: 'sAMAccountName',
  attr_full_name: 'displayName',
  attr_email: 'mail',
  attr_department: 'department',
  bind_dn: null,
  timeout_seconds: 5,
};

function get(values: object, key: string): unknown {
  return new Map(Object.entries(values)).get(key);
}

export function authMode(values: object): 'local' | 'ad' {
  return get(values, 'auth.mode') === 'ad' ? 'ad' : 'local';
}

export function controllerText(c: { host: string; port: number }): string {
  return `${c.host}:${c.port}`;
}

/** «dc1.corp.local:636» → {host, port}; без порта — порт протокола; иначе null. */
export function parseController(text: string, protocol: Protocol): { host: string; port: number } | null {
  const [host = '', portText, ...rest] = text.trim().split(':');
  if (rest.length > 0 || !/^[A-Za-z0-9.-]{1,255}$/.test(host)) return null;
  if (portText !== undefined && !/^\d{1,5}$/.test(portText)) return null;
  const port = portText ? Number(portText) : protocol === 'ldaps' ? DEFAULT_PORT.ldaps : DEFAULT_PORT.starttls;
  return port >= 1 && port <= 65535 ? { host, port } : null;
}

export function formOf(values: object): AuthForm {
  const conn = { ...DEFAULT_CONNECTION, ...((get(values, 'auth.ad.connection') as Partial<Connection>) ?? {}) };
  const mapping = (get(values, 'auth.ad.role_mapping') as RoleMapping | null) ?? { enabled: false, mappings: [] };
  const firstOf = (role: MappedRole) => mapping.mappings.find((m) => m.role === role);
  const mod = firstOf('moderator');
  const pre = firstOf('presale');
  const password = get(values, 'auth.ad.bind_password');
  return {
    controllers: conn.controllers.length ? conn.controllers.map(controllerText) : [''],
    protocol: conn.protocol,
    caCert: conn.ca_cert_pem,
    baseDn: conn.base_dn ?? '',
    userFilter: conn.user_filter,
    loginAttribute: conn.login_attribute,
    attrFullName: conn.attr_full_name,
    attrEmail: conn.attr_email,
    attrDepartment: conn.attr_department,
    bindDn: conn.bind_dn ?? '',
    timeout: conn.timeout_seconds,
    bindPassword: null,
    passwordSet: Boolean(password && typeof password === 'object' && get(password, 'set') === true),
    accessGroups: (() => {
      const groups = (get(values, 'auth.ad.access_groups') as string[] | null) ?? [];
      return groups.length ? groups : [''];
    })(),
    mappingEnabled: mapping.enabled,
    moderatorGroup: mod?.group_dn ?? '',
    presaleGroup: pre?.group_dn ?? '',
    extraMappings: mapping.mappings.filter((m) => m !== mod && m !== pre),
  };
}

const filled = (s: string) => s.trim() !== '';

/** Значения раздела `auth` для PUT и для «Проверить подключение» (без `auth.mode`). */
export function valuesOf(form: AuthForm): Record<string, unknown> {
  const controllers = form.controllers
    .filter(filled)
    .map((c) => parseController(c, form.protocol))
    .filter((c): c is { host: string; port: number } => c !== null);
  const mappings: RoleMapping['mappings'] = [
    ...(filled(form.moderatorGroup) ? [{ group_dn: form.moderatorGroup.trim(), role: 'moderator' as const }] : []),
    ...(filled(form.presaleGroup) ? [{ group_dn: form.presaleGroup.trim(), role: 'presale' as const }] : []),
    ...form.extraMappings,
  ];
  return {
    'auth.ad.connection': {
      controllers,
      protocol: form.protocol,
      ca_cert_pem: form.caCert,
      base_dn: filled(form.baseDn) ? form.baseDn.trim() : null,
      user_filter: form.userFilter.trim(),
      login_attribute: form.loginAttribute,
      attr_full_name: form.attrFullName.trim(),
      attr_email: form.attrEmail.trim(),
      attr_department: form.attrDepartment.trim(),
      bind_dn: filled(form.bindDn) ? form.bindDn.trim() : null,
      timeout_seconds: form.timeout,
    } satisfies Connection,
    'auth.ad.access_groups': [...new Set(form.accessGroups.filter(filled).map((g) => g.trim()))],
    'auth.ad.role_mapping': { enabled: form.mappingEnabled, mappings } satisfies RoleMapping,
    ...(form.bindPassword !== null ? { 'auth.ad.bind_password': form.bindPassword } : {}),
  };
}

/** Подпись параметров: при любом изменении проверки нужно пройти заново (FR-AUTH-AD-03). */
export function signature(form: AuthForm): string {
  return JSON.stringify(valuesOf(form));
}

export type FieldError =
  | 'controllers'
  | 'controller'
  | 'baseDn'
  | 'userFilter'
  | 'bindDn'
  | 'bindPassword'
  | 'accessGroups'
  | 'mapping'
  | 'timeout';

/**
 * CR-009 · сервер (контроллеры) или сервисная учётка не те, что сохранены: сохранённый пароль
 * сервер не подставит — его нужно ввести заново.
 */
export function serverChanged(form: AuthForm, initial: AuthForm): boolean {
  const servers = (f: AuthForm) => JSON.stringify(f.controllers.filter(filled).map((c) => c.trim()));
  return servers(form) !== servers(initial) || form.bindDn.trim() !== initial.bindDn.trim();
}

/** Пароль задан на сервере и его можно не вводить. */
export function keepsPassword(form: AuthForm, initial: AuthForm = form): boolean {
  return form.bindPassword === null && form.passwordSet && !serverChanged(form, initial);
}

/** Ошибки полей; пустой список — форму можно проверять и сохранять. */
export function validate(form: AuthForm, initial: AuthForm = form): FieldError[] {
  const errors: FieldError[] = [];
  const controllers = form.controllers.filter(filled);
  if (controllers.length === 0) errors.push('controllers');
  else if (controllers.some((c) => parseController(c, form.protocol) === null)) errors.push('controller');
  if (!filled(form.baseDn)) errors.push('baseDn');
  if (!form.userFilter.includes('{login}')) errors.push('userFilter');
  if (!filled(form.bindDn)) errors.push('bindDn');
  if (form.bindPassword !== null ? form.bindPassword === '' : !keepsPassword(form, initial))
    errors.push('bindPassword');
  if (!form.accessGroups.some(filled)) errors.push('accessGroups');
  if (form.mappingEnabled && !filled(form.moderatorGroup) && !filled(form.presaleGroup)) errors.push('mapping');
  if (!Number.isInteger(form.timeout) || form.timeout < 1 || form.timeout > 60) errors.push('timeout');
  return errors;
}

/** «за 0,2 с» — время ответа каталога. */
export function seconds(ms: number): string {
  return (ms / 1000).toLocaleString('ru-RU', { maximumFractionDigits: 1 });
}

/** Короткое имя группы для подсказок: «CN=APP-Users,OU=…» → «APP-Users». */
export function groupName(dn: string): string {
  return /^CN=([^,]+)/i.exec(dn)?.[1] ?? dn;
}

/** Сертификат PEM: начинается с BEGIN CERTIFICATE и не больше 64 КБ (SEC-WEB-08). */
export function certProblem(text: string, size: number): 'size' | 'format' | null {
  if (size > CA_MAX_BYTES) return 'size';
  return text.trimStart().startsWith('-----BEGIN CERTIFICATE-----') ? null : 'format';
}
