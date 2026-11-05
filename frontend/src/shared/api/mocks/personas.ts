/**
 * FE-001 · роли переключателя моков и права, которые из них следуют.
 *
 * Права считаются по `contracts/permissions.yaml` (раздел grants): системные роли дают выдачи
 * с context: global, проектная роль — выдачи с context: member в своём проекте, руководитель
 * пресейла — context: any_project в любом проекте (FR-PORT-01). Области (своя дисциплина,
 * автор) и статусы проекта (3.4) моки не проверяют — это делает сервер; моки повторяют
 * главное для интерфейса: есть право или нет, видны ли деньги (SEC-AUTHZ-04).
 */
import { permissionsDoc, type Grant } from './contract';
import { uuidFrom } from './ids';

export type ProjectRole = 'moderator' | 'expert' | 'presale';

export type Membership = { role: ProjectRole; discipline: string | null; isReviewer: boolean };

export type Persona = {
  key: PersonaKey;
  login: string;
  fullName: string;
  initials: string;
  systemRoles: string[];
  /** ключ проекта демо-данных → роль в нём */
  projects: Record<string, Membership>;
  /** подпись в переключателе — ключ i18n `mock.persona.<key>` */
};

export const PERSONA_KEYS = [
  'expert',
  'moderator',
  'presale',
  'presale_head',
  'admin',
  'superadmin',
  'auditor',
] as const;
export type PersonaKey = (typeof PERSONA_KEYS)[number];

const member = (role: ProjectRole, discipline: string | null = null, isReviewer = false) => ({
  role,
  discipline,
  isReviewer,
});

export const PERSONAS: Record<PersonaKey, Persona> = {
  // SPEC 11.3: в «Портале дилеров» Иванов — эксперт Бэкенда и ревьюер, в «Интеграции с ФНС» —
  // модератор (у него системная роль «Модератор»)
  expert: {
    key: 'expert',
    login: 'i.ivanov',
    fullName: 'И. Иванов',
    initials: 'ИИ',
    systemRoles: ['moderator'],
    projects: { portal: member('expert', 'd-backend', true), fns: member('moderator') },
  },
  moderator: {
    key: 'moderator',
    login: 'a.smirnova',
    fullName: 'А. Смирнова',
    initials: 'АС',
    systemRoles: ['moderator'],
    projects: { portal: member('moderator') },
  },
  presale: {
    key: 'presale',
    login: 'p.sidorov',
    fullName: 'П. Сидоров',
    initials: 'ПС',
    systemRoles: ['presale'],
    projects: { portal: member('presale'), fns: member('presale') },
  },
  presale_head: {
    key: 'presale_head',
    login: 'e.sokolova',
    fullName: 'Е. Соколова',
    initials: 'ЕС',
    systemRoles: ['presale_head'],
    projects: {},
  },
  admin: {
    key: 'admin',
    login: 'v.kozlov',
    fullName: 'В. Козлов',
    initials: 'ВК',
    systemRoles: ['admin'],
    projects: {},
  },
  superadmin: {
    key: 'superadmin',
    login: 'superadmin',
    fullName: 'Суперадминистратор',
    initials: 'СА',
    systemRoles: ['superadmin'],
    projects: {},
  },
  auditor: {
    key: 'auditor',
    login: 'l.frolova',
    fullName: 'Л. Фролова',
    initials: 'ЛФ',
    systemRoles: ['security_auditor'],
    projects: {},
  },
};

export const personaId = (p: Persona) => uuidFrom('user', p.login);

const PROJECT_ROLE_GRANTS: Record<ProjectRole, string> = {
  moderator: 'project_moderator',
  expert: 'expert',
  presale: 'project_presale',
};

function grantsOf(subject: string): Grant[] {
  const out: Grant[] = [];
  for (const grant of permissionsDoc.grants[subject] ?? []) {
    if (grant.inherit) out.push(...grantsOf(grant.inherit));
    else out.push(grant);
  }
  return out;
}

function allowed(grant: Grant, persona: Persona): boolean {
  if (grant.unless_role?.some((r) => persona.systemRoles.includes(r))) return false;
  if (grant.requires_system_role && !persona.systemRoles.includes(grant.requires_system_role)) {
    return false;
  }
  // моки работают в режиме входа «Приложение»: права «только в режиме AD» не выдаются
  return !grant.requires_setting;
}

export type Access = {
  /** доступ к проекту: участник, руководитель пресейла или нет доступа (→ 404) */
  access: 'member' | 'presale_head' | null;
  permissions: Set<string>;
};

/** Права персоны глобально (project = null) или в проекте с ключом демо-данных. */
export function accessOf(persona: Persona, project: string | null): Access {
  const permissions = new Set<string>();
  const add = (grants: Grant[], contexts: string[]) => {
    for (const g of grants) {
      if (g.permission && contexts.includes(g.context ?? 'global') && allowed(g, persona)) {
        permissions.add(g.permission);
      }
    }
  };
  for (const role of ['user', ...persona.systemRoles]) add(grantsOf(role), ['global']);
  if (project === null) return { access: null, permissions };

  const membership = persona.projects[project];
  if (membership) {
    const subject = membership.isReviewer ? 'reviewer' : PROJECT_ROLE_GRANTS[membership.role];
    add(grantsOf(subject), ['member']);
    return { access: 'member', permissions };
  }
  if (persona.systemRoles.includes('presale_head')) {
    add(grantsOf('presale_head'), ['any_project']);
    return { access: 'presale_head', permissions };
  }
  return { access: null, permissions };
}

// --- выбранная роль ------------------------------------------------------------------------

const STORAGE_KEY = 'estimator.mock.persona';
let current: PersonaKey = 'expert';

function isPersonaKey(value: unknown): value is PersonaKey {
  return typeof value === 'string' && (PERSONA_KEYS as readonly string[]).includes(value);
}

/** Роль из localStorage (если браузер его не даёт — роль по умолчанию, эксперт). */
export function loadPersona(): PersonaKey {
  try {
    const saved = window.localStorage.getItem(STORAGE_KEY);
    if (isPersonaKey(saved)) current = saved;
  } catch {
    // приватный режим или запрет хранилища — остаётся роль в памяти
  }
  return current;
}

export function currentPersona(): Persona {
  return PERSONAS[current];
}

export function setPersona(key: PersonaKey): void {
  current = key;
  try {
    window.localStorage.setItem(STORAGE_KEY, key);
  } catch {
    // см. loadPersona
  }
}
