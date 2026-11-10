/**
 * FE-071 · справочники SPEC 7.5: фазы, дисциплины, типы узлов (нормы списком), профили (цепочка
 * типов), контрольные соотношения, метки, валюты, ставки НДС, причины проигрыша. Каждый — набор
 * полей и правил для шаблона «список + форма справа» (Dictionary.tsx).
 */
import { Button, Checkbox, MultiSelect, Select, Text, TextInput } from '@mantine/core';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';

import { api } from '../../../shared/api/client';
import { call } from '../../../shared/api/problem';
import { NODE_TYPE_ICON_KEYS, nodeTypeSymbol } from '../../../shared/ui/icons/nodeTypes';
import { Dictionary, type DictConfig } from './Dictionary';
import {
  CODE_RE,
  HEX_RE,
  chainText,
  currencyLocks,
  dec,
  decimal,
  dictKey,
  hoursValid,
  nodeTypeLocks,
  pctValid,
  phaseLocks,
  profileLocks,
  profilesOf,
  vatLocks,
  type Currency,
  type Discipline,
  type LossReason,
  type NodeType,
  type NodeTypeIcon,
  type Phase,
  type Profile,
  type Ratio,
  type Tag,
  type VatRate,
} from './dictionaries';

const all = { params: { query: { include_inactive: true } } };
const loadPhases = () => call(() => api.GET('/admin/phases', all));
const loadDisciplines = () => call(() => api.GET('/admin/disciplines', all));
// ответы openapi-fetch разворачивают тип DecimalString — приводим к типам схемы, как в RatioList
const typed = <T,>(p: Promise<unknown>) => p as Promise<T>;
const loadNodeTypes = () => typed<{ items: NodeType[] }>(call(() => api.GET('/admin/node-types', all)));
const loadProfiles = () => call(() => api.GET('/admin/profiles', all));
const byId = (id: string) => ({ params: { path: { id } } });

/** Дисциплины, профили и типы узлов — подписи и выбор в других справочниках. */
export function useLookups() {
  const disciplines = useQuery({ queryKey: dictKey('disciplines'), queryFn: loadDisciplines });
  const profiles = useQuery({ queryKey: dictKey('profiles'), queryFn: loadProfiles });
  const types = useQuery({ queryKey: dictKey('node-types'), queryFn: loadNodeTypes });
  return {
    disciplines: disciplines.data?.items ?? [],
    profiles: profiles.data?.items ?? [],
    types: types.data?.items ?? [],
  };
}
export type Lookups = ReturnType<typeof useLookups>;

const name = (items: readonly { id: string; name: string }[], id: string | null) =>
  items.find((i) => i.id === id)?.name ?? '—';

function Color({ value, onChange, label }: { value: string; onChange: (v: string) => void; label: string }) {
  const { t } = useTranslation();
  return (
    <TextInput
      label={label}
      required
      className="mono"
      value={value}
      maxLength={7}
      error={value && !HEX_RE.test(value) ? t('admin.dict.colorError') : null}
      leftSection={<span className="adm-swatch" style={{ background: HEX_RE.test(value) ? value : 'transparent' }} />}
      onChange={(e) => onChange(e.currentTarget.value.trim())}
    />
  );
}

function Name({ value, max, set }: { value: string; max: number; set: (v: string) => void }) {
  const { t } = useTranslation();
  return (
    <TextInput
      label={t('admin.dict.f.name')}
      required
      value={value}
      maxLength={max}
      onChange={(e) => set(e.currentTarget.value)}
    />
  );
}

// --- Фазы ---------------------------------------------------------------------------------------

type PhaseDraft = { name: string; sort: string; cross: boolean };

function PhaseFields({
  draft,
  set,
  record,
}: {
  draft: PhaseDraft;
  set: (p: Partial<PhaseDraft>) => void;
  record: Phase | null;
}) {
  const { t } = useTranslation();
  return (
    <>
      <Name value={draft.name} max={100} set={(v) => set({ name: v })} />
      <TextInput
        label={t('admin.dict.f.order')}
        inputMode="numeric"
        value={draft.sort}
        maxLength={4}
        onChange={(e) => set({ sort: e.currentTarget.value.replace(/\D/g, '') })}
      />
      <Checkbox
        mt="xs"
        label={t('admin.dict.f.crossCutting')}
        description={t('admin.dict.f.crossCuttingHint')}
        checked={draft.cross}
        disabled={record?.is_cross_cutting === true}
        onChange={(e) => set({ cross: e.currentTarget.checked })}
      />
    </>
  );
}

const phases: DictConfig<Phase, PhaseDraft> = {
  kind: 'phases',
  load: loadPhases,
  keyOf: (r) => r.id,
  nameOf: (r) => r.name,
  headers: ['admin.dict.f.name', 'admin.dict.f.order', 'admin.dict.f.crossShort'],
  cells: (r) => [r.name, r.sort_order, r.is_cross_cutting ? '✓' : ''],
  empty: { name: '', sort: '', cross: false },
  toDraft: (r) => ({ name: r.name, sort: String(r.sort_order), cross: r.is_cross_cutting }),
  valid: (d) => d.name.trim() !== '',
  Fields: PhaseFields,
  save: (d, r) => {
    const body = {
      name: d.name.trim(),
      is_cross_cutting: d.cross,
      is_active: d.is_active,
      ...(d.sort ? { sort_order: Number(d.sort) } : {}),
    };
    return call(() =>
      r ? api.PATCH('/admin/phases/{id}', { ...byId(r.id), body }) : api.POST('/admin/phases', { body }),
    );
  },
  remove: (r) => call(() => api.DELETE('/admin/phases/{id}', byId(r.id))),
  locks: phaseLocks,
};

// --- Дисциплины ---------------------------------------------------------------------------------

type DisciplineDraft = { name: string; short: string; color: string; profile: string | null };

function DisciplineFields({
  draft,
  set,
  record,
}: {
  draft: DisciplineDraft;
  set: (p: Partial<DisciplineDraft>) => void;
  record: Discipline | null;
}) {
  const { t } = useTranslation();
  const lk = useLookups();
  return (
    <>
      <Name value={draft.name} max={100} set={(v) => set({ name: v })} />
      <TextInput
        label={t('admin.dict.f.short')}
        description={t('admin.dict.f.shortHint')}
        required
        value={draft.short}
        maxLength={12}
        onChange={(e) => set({ short: e.currentTarget.value })}
      />
      <Color label={t('admin.dict.f.color')} value={draft.color} onChange={(v) => set({ color: v })} />
      {record ? (
        <Select
          label={t('admin.dict.f.defaultProfile')}
          description={t('admin.dict.f.defaultProfileHint')}
          value={draft.profile}
          data={profilesOf(lk.profiles, record.id)
            .filter((p) => p.is_active)
            .map((p) => ({ value: p.id, label: p.name }))}
          onChange={(v) => set({ profile: v })}
        />
      ) : (
        <Text size="xs" c="dimmed">
          {t('admin.dict.f.profileLater')}
        </Text>
      )}
    </>
  );
}

function ProfileName({ id }: { id: string | null }) {
  const lk = useLookups();
  return <>{name(lk.profiles, id)}</>;
}

const disciplines: DictConfig<Discipline, DisciplineDraft> = {
  kind: 'disciplines',
  load: loadDisciplines,
  keyOf: (r) => r.id,
  nameOf: (r) => r.name,
  headers: ['admin.dict.f.name', 'admin.dict.f.short', 'admin.dict.f.defaultProfile'],
  cells: (r) => [
    r.name,
    <span key="s" className="adm-chip" style={{ borderColor: r.color }}>
      <span className="adm-swatch" style={{ background: r.color }} />
      {r.short_name}
    </span>,
    <ProfileName key="p" id={r.default_profile_id} />,
  ],
  empty: { name: '', short: '', color: '#868e96', profile: null },
  toDraft: (r) => ({ name: r.name, short: r.short_name, color: r.color, profile: r.default_profile_id }),
  valid: (d) => d.name.trim() !== '' && d.short.trim() !== '' && HEX_RE.test(d.color),
  Fields: DisciplineFields,
  save: (d, r) => {
    const body = { name: d.name.trim(), short_name: d.short.trim(), color: d.color, is_active: d.is_active };
    return call(() =>
      r
        ? api.PATCH('/admin/disciplines/{id}', { ...byId(r.id), body: { ...body, default_profile_id: d.profile } })
        : api.POST('/admin/disciplines', { body }),
    );
  },
  remove: (r) => call(() => api.DELETE('/admin/disciplines/{id}', byId(r.id))),
};

// --- Типы узлов ---------------------------------------------------------------------------------

type NormDraft = { label: string; o: string; r: string; p: string };
type NodeTypeDraft = { name: string; icon: NodeTypeIcon; norms: NormDraft[] };

export const MAX_NORMS = 20;

/** Норма заполнена: подпись и O ≤ R ≤ P в часах. */
export const normValid = (n: NormDraft) =>
  n.label.trim() !== '' &&
  [n.o, n.r, n.p].every(hoursValid) &&
  Number(decimal(n.o)) <= Number(decimal(n.r)) &&
  Number(decimal(n.r)) <= Number(decimal(n.p));

function NodeTypeFields({ draft, set }: { draft: NodeTypeDraft; set: (p: Partial<NodeTypeDraft>) => void }) {
  const { t } = useTranslation();
  const norm = (i: number, patch: Partial<NormDraft>) =>
    set({ norms: draft.norms.map((n, j) => (j === i ? { ...n, ...patch } : n)) });
  return (
    <>
      <Name value={draft.name} max={50} set={(v) => set({ name: v })} />
      <Text size="sm" fw={500} id="dict-icon-label">
        {t('admin.dict.f.icon')}
      </Text>
      <div className="icon-grid" role="radiogroup" aria-labelledby="dict-icon-label">
        {NODE_TYPE_ICON_KEYS.map((key) => (
          <button
            key={key}
            type="button"
            role="radio"
            aria-checked={draft.icon === key}
            aria-label={t(`menu.icon.${key}`)}
            title={t(`menu.icon.${key}`)}
            className={draft.icon === key ? 'icon-opt sel' : 'icon-opt'}
            onClick={() => set({ icon: key })}
          >
            {nodeTypeSymbol(key)}
          </button>
        ))}
      </div>
      <Text size="sm" fw={500} mt="xs">
        {t('admin.dict.f.norms')}
      </Text>
      <Text size="xs" c="dimmed">
        {t('admin.dict.f.normsHint')}
      </Text>
      {draft.norms.length > 0 ? (
        <table className="adm-norms">
          <thead>
            <tr>
              <th>{t('admin.dict.f.normLabel')}</th>
              <th>O</th>
              <th>R</th>
              <th>P</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {draft.norms.map((n, i) => (
              <tr key={i} className={normValid(n) || !(n.label + n.o + n.r + n.p).trim() ? undefined : 'bad'}>
                <td>
                  <TextInput
                    size="xs"
                    aria-label={t('admin.dict.f.normLabelN', { n: i + 1 })}
                    value={n.label}
                    maxLength={50}
                    onChange={(e) => norm(i, { label: e.currentTarget.value })}
                  />
                </td>
                {(['o', 'r', 'p'] as const).map((k) => (
                  <td key={k}>
                    <TextInput
                      size="xs"
                      className="num"
                      aria-label={`${k.toUpperCase()} ${i + 1}`}
                      value={k === 'o' ? n.o : k === 'r' ? n.r : n.p}
                      maxLength={8}
                      onChange={(e) => norm(i, { [k]: e.currentTarget.value })}
                    />
                  </td>
                ))}
                <td>
                  <button
                    type="button"
                    className="btn-link"
                    aria-label={t('admin.dict.f.normRemove', { n: i + 1 })}
                    onClick={() => set({ norms: draft.norms.filter((_, j) => j !== i) })}
                  >
                    ✕
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
      <Button
        size="xs"
        variant="default"
        disabled={draft.norms.length >= MAX_NORMS}
        onClick={() => set({ norms: [...draft.norms, { label: '', o: '', r: '', p: '' }] })}
      >
        + {t('admin.dict.f.normAdd')}
      </Button>
    </>
  );
}

const nodeTypes: DictConfig<NodeType, NodeTypeDraft> = {
  kind: 'node-types',
  load: loadNodeTypes,
  keyOf: (r) => r.id,
  nameOf: (r) => r.name,
  headers: ['admin.dict.f.name', 'admin.dict.f.norms'],
  cells: (r) => [
    <span key="n">
      <span className="adm-icon" aria-hidden>
        {nodeTypeSymbol(r.icon)}
      </span>
      {r.name}
    </span>,
    r.norms.length ? r.norms.map((n) => `${n.label} ${n.o}–${n.r}–${n.p}`).join('; ') : '—',
  ],
  empty: { name: '', icon: 'work', norms: [] },
  toDraft: (r) => ({
    name: r.name,
    icon: r.icon as NodeTypeIcon,
    norms: r.norms.map((n) => ({ label: n.label, o: n.o, r: n.r, p: n.p })),
  }),
  valid: (d) => d.name.trim() !== '' && d.norms.every(normValid),
  Fields: NodeTypeFields,
  save: (d, r) => {
    const body = {
      name: d.name.trim(),
      icon: d.icon,
      is_active: d.is_active,
      norms: d.norms.map((n) => ({ label: n.label.trim(), o: dec(n.o), r: dec(n.r), p: dec(n.p) })),
    };
    return typed<NodeType>(
      call(() =>
        r ? api.PATCH('/admin/node-types/{id}', { ...byId(r.id), body }) : api.POST('/admin/node-types', { body }),
      ),
    );
  },
  remove: (r) => call(() => api.DELETE('/admin/node-types/{id}', byId(r.id))),
  locks: nodeTypeLocks,
};

// --- Профили ------------------------------------------------------------------------------------

type ProfileDraft = { discipline: string | null; name: string; chain: string[] };

export const MAX_CHAIN = 8;

function ProfileFields({ draft, set }: { draft: ProfileDraft; set: (p: Partial<ProfileDraft>) => void }) {
  const { t } = useTranslation();
  const lk = useLookups();
  const active = lk.types.filter((x) => x.is_active && x.project_id === null);
  return (
    <>
      <Select
        label={t('admin.dict.f.discipline')}
        required
        value={draft.discipline}
        data={lk.disciplines.filter((d) => d.is_active).map((d) => ({ value: d.id, label: d.name }))}
        onChange={(v) => set({ discipline: v })}
      />
      <Name value={draft.name} max={100} set={(v) => set({ name: v })} />
      <Text size="sm" fw={500}>
        {t('admin.dict.f.chain')}
      </Text>
      <Text size="xs" c="dimmed">
        {t('admin.dict.f.chainHint')}
      </Text>
      <ol className="adm-chain" aria-label={t('admin.dict.f.chain')}>
        {draft.chain.map((id, i) => (
          <li key={`${id}-${i}`}>
            {name(lk.types, id)}
            <button
              type="button"
              className="btn-link"
              aria-label={t('admin.dict.f.chainRemove', { name: name(lk.types, id) })}
              onClick={() => set({ chain: draft.chain.filter((_, j) => j !== i) })}
            >
              ✕
            </button>
          </li>
        ))}
      </ol>
      <Select
        aria-label={t('admin.dict.f.chainAdd')}
        placeholder={t('admin.dict.f.chainAdd')}
        value={null}
        disabled={draft.chain.length >= MAX_CHAIN}
        data={active.map((x) => ({ value: x.id, label: x.name }))}
        onChange={(v) => (v ? set({ chain: [...draft.chain, v] }) : undefined)}
      />
    </>
  );
}

function DisciplineName({ id }: { id: string }) {
  const lk = useLookups();
  return <>{name(lk.disciplines, id)}</>;
}

function Chain({ chain }: { chain: string[] }) {
  const lk = useLookups();
  return <>{chainText(chain, lk.types)}</>;
}

/** Плашка «по умолчанию» у профиля зависит от дисциплин — поэтому правило строится из справочника. */
function profilesConfig(lk: Lookups): DictConfig<Profile, ProfileDraft> {
  return {
    kind: 'profiles',
    load: loadProfiles,
    keyOf: (r) => r.id,
    nameOf: (r) => r.name,
    headers: ['admin.dict.f.name', 'admin.dict.f.discipline', 'admin.dict.f.chain'],
    cells: (r) => [r.name, <DisciplineName key="d" id={r.discipline_id} />, <Chain key="c" chain={r.type_chain} />],
    empty: { discipline: null, name: '', chain: [] },
    toDraft: (r) => ({ discipline: r.discipline_id, name: r.name, chain: [...r.type_chain] }),
    valid: (d) => d.discipline !== null && d.name.trim() !== '' && d.chain.length >= 1 && d.chain.length <= MAX_CHAIN,
    Fields: ProfileFields,
    save: (d, r) => {
      const body = {
        discipline_id: d.discipline ?? '',
        name: d.name.trim(),
        type_chain: d.chain,
        is_active: d.is_active,
      };
      return call(() =>
        r ? api.PATCH('/admin/profiles/{id}', { ...byId(r.id), body }) : api.POST('/admin/profiles', { body }),
      );
    },
    remove: (r) => call(() => api.DELETE('/admin/profiles/{id}', byId(r.id))),
    locks: (r) => profileLocks(r, lk.disciplines),
  };
}

// --- Контрольные соотношения --------------------------------------------------------------------

type RatioDraft = { a: string | null; b: string[]; min: string; max: string };

export const ratioValid = (d: RatioDraft) =>
  d.a !== null &&
  d.b.length > 0 &&
  !d.b.includes(d.a) &&
  pctValid(d.min) &&
  pctValid(d.max) &&
  Number(decimal(d.min)) <= Number(decimal(d.max));

function RatioFields({ draft, set }: { draft: RatioDraft; set: (p: Partial<RatioDraft>) => void }) {
  const { t } = useTranslation();
  const lk = useLookups();
  const options = lk.disciplines.filter((d) => d.is_active).map((d) => ({ value: d.id, label: d.name }));
  const order = draft.min && draft.max && pctValid(draft.min) && pctValid(draft.max);
  return (
    <>
      <Select
        label={t('admin.dict.f.ratioA')}
        required
        value={draft.a}
        data={options}
        onChange={(v) => set({ a: v, b: draft.b.filter((x) => x !== v) })}
      />
      <MultiSelect
        label={t('admin.dict.f.ratioB')}
        description={t('admin.dict.f.ratioBHint')}
        required
        value={draft.b}
        data={options.filter((o) => o.value !== draft.a)}
        onChange={(v) => set({ b: v })}
      />
      <div className="adm-pair">
        <TextInput
          label={t('admin.dict.f.min')}
          required
          value={draft.min}
          maxLength={6}
          rightSection="%"
          error={draft.min && !pctValid(draft.min) ? t('admin.dict.pctError') : null}
          onChange={(e) => set({ min: e.currentTarget.value })}
        />
        <TextInput
          label={t('admin.dict.f.max')}
          required
          value={draft.max}
          maxLength={6}
          rightSection="%"
          error={
            draft.max && !pctValid(draft.max)
              ? t('admin.dict.pctError')
              : order && Number(decimal(draft.min)) > Number(decimal(draft.max))
                ? t('admin.dict.minMaxError')
                : null
          }
          onChange={(e) => set({ max: e.currentTarget.value })}
        />
      </div>
    </>
  );
}

function Disciplines({ ids }: { ids: string[] }) {
  const lk = useLookups();
  return <>{ids.map((id) => name(lk.disciplines, id)).join(' + ')}</>;
}

/** Название соотношения для поиска и заголовка формы — «QA к Бэкенд + Фронтенд». */
function ratiosConfig(lk: Lookups): DictConfig<Ratio & { name?: string }, RatioDraft> {
  const title = (r: Ratio) =>
    `${name(lk.disciplines, r.discipline_a_id)} : ${r.disciplines_b.map((id) => name(lk.disciplines, id)).join(' + ')}`;
  return {
    kind: 'ratios',
    load: () => typed<{ items: Ratio[] }>(call(() => api.GET('/admin/ratios', all))),
    keyOf: (r) => r.id,
    nameOf: title,
    headers: ['admin.dict.f.ratioA', 'admin.dict.f.ratioB', 'admin.dict.f.norm'],
    cells: (r) => [
      <DisciplineName key="a" id={r.discipline_a_id} />,
      <Disciplines key="b" ids={r.disciplines_b} />,
      `${r.min_pct}–${r.max_pct}%`,
    ],
    empty: { a: null, b: [], min: '', max: '' },
    toDraft: (r) => ({ a: r.discipline_a_id, b: [...r.disciplines_b], min: r.min_pct, max: r.max_pct }),
    valid: ratioValid,
    Fields: RatioFields,
    save: (d, r) => {
      const body = {
        discipline_a_id: d.a ?? '',
        disciplines_b: d.b,
        min_pct: dec(d.min),
        max_pct: dec(d.max),
        is_active: d.is_active,
      };
      return typed<Ratio>(
        call(() =>
          r ? api.PATCH('/admin/ratios/{id}', { ...byId(r.id), body }) : api.POST('/admin/ratios', { body }),
        ),
      );
    },
    remove: (r) => call(() => api.DELETE('/admin/ratios/{id}', byId(r.id))),
  };
}

// --- Метки --------------------------------------------------------------------------------------

const CATEGORIES = ['assumption', 'constraint', 'risk', 'tech'] as const;
type TagDraft = { name: string; short: string; color: string; category: Tag['category'] };

function TagFields({ draft, set }: { draft: TagDraft; set: (p: Partial<TagDraft>) => void }) {
  const { t } = useTranslation();
  return (
    <>
      <Name value={draft.name} max={50} set={(v) => set({ name: v })} />
      <TextInput
        label={t('admin.dict.f.tagShort')}
        description={t('admin.dict.f.tagShortHint')}
        required
        value={draft.short}
        maxLength={12}
        onChange={(e) => set({ short: e.currentTarget.value })}
      />
      <Color label={t('admin.dict.f.color')} value={draft.color} onChange={(v) => set({ color: v })} />
      <Select
        label={t('admin.dict.f.category')}
        description={t('admin.dict.f.categoryHint')}
        required
        allowDeselect={false}
        value={draft.category}
        data={CATEGORIES.map((c) => ({ value: c, label: t(`admin.dict.cat.${c}`) }))}
        onChange={(v) => (v ? set({ category: v as Tag['category'] }) : undefined)}
      />
    </>
  );
}

function CategoryCell({ category }: { category: Tag['category'] }) {
  const { t } = useTranslation();
  return <>{t(`admin.dict.cat.${category}`)}</>;
}

const tags: DictConfig<Tag, TagDraft> = {
  kind: 'tags',
  load: () => call(() => api.GET('/admin/tags', all)),
  keyOf: (r) => r.id,
  nameOf: (r) => r.name,
  headers: ['admin.dict.f.name', 'admin.dict.f.tagShort', 'admin.dict.f.category'],
  cells: (r) => [
    r.name,
    <span key="s" className="adm-chip" style={{ borderColor: r.color, color: r.color }}>
      {r.short_name}
    </span>,
    <CategoryCell key="c" category={r.category} />,
  ],
  empty: { name: '', short: '', color: '#868e96', category: 'tech' },
  toDraft: (r) => ({ name: r.name, short: r.short_name, color: r.color, category: r.category }),
  valid: (d) => d.name.trim() !== '' && d.short.trim() !== '' && HEX_RE.test(d.color),
  Fields: TagFields,
  save: (d, r) => {
    const body = {
      name: d.name.trim(),
      short_name: d.short.trim(),
      color: d.color,
      category: d.category,
      is_active: d.is_active,
    };
    return call(() => (r ? api.PATCH('/admin/tags/{id}', { ...byId(r.id), body }) : api.POST('/admin/tags', { body })));
  },
  remove: (r) => call(() => api.DELETE('/admin/tags/{id}', byId(r.id))),
};

// --- Валюты -------------------------------------------------------------------------------------

type CurrencyDraft = { code: string; symbol: string };

function CurrencyFields({
  draft,
  set,
  record,
}: {
  draft: CurrencyDraft;
  set: (p: Partial<CurrencyDraft>) => void;
  record: Currency | null;
}) {
  const { t } = useTranslation();
  return (
    <>
      <TextInput
        label={t('admin.dict.f.code')}
        description={record ? null : t('admin.dict.f.codeHint')}
        required
        className="mono"
        value={draft.code}
        maxLength={3}
        disabled={record !== null}
        error={draft.code && !record && !CODE_RE.test(draft.code) ? t('admin.dict.codeError') : null}
        onChange={(e) => set({ code: e.currentTarget.value.toUpperCase() })}
      />
      <TextInput
        label={t('admin.dict.f.symbol')}
        value={draft.symbol}
        maxLength={8}
        onChange={(e) => set({ symbol: e.currentTarget.value })}
      />
    </>
  );
}

const currencies: DictConfig<Currency & { name?: string }, CurrencyDraft> = {
  kind: 'currencies',
  load: () => call(() => api.GET('/admin/currencies', all)),
  keyOf: (r) => r.code,
  nameOf: (r) => r.code,
  headers: ['admin.dict.f.code', 'admin.dict.f.symbol'],
  cells: (r) => [r.code, r.symbol || '—'],
  empty: { code: '', symbol: '' },
  toDraft: (r) => ({ code: r.code, symbol: r.symbol }),
  valid: (d) => CODE_RE.test(d.code),
  Fields: CurrencyFields,
  save: (d, r) =>
    call(() =>
      r
        ? api.PATCH('/admin/currencies/{code}', {
            params: { path: { code: r.code } },
            body: { symbol: d.symbol.trim(), is_active: d.is_active },
          })
        : api.POST('/admin/currencies', { body: { code: d.code, symbol: d.symbol.trim(), is_active: d.is_active } }),
    ),
  remove: (r) => call(() => api.DELETE('/admin/currencies/{code}', { params: { path: { code: r.code } } })),
  locks: currencyLocks,
};

// --- Ставки НДС ---------------------------------------------------------------------------------

/** `noVat` — запись «Без НДС»: процента у неё нет. */
type VatDraft = { name: string; percent: string; isDefault: boolean; noVat: boolean };

function VatFields({
  draft,
  set,
  record,
}: {
  draft: VatDraft;
  set: (p: Partial<VatDraft>) => void;
  record: VatRate | null;
}) {
  const { t } = useTranslation();
  return (
    <>
      <Name value={draft.name} max={50} set={(v) => set({ name: v })} />
      {draft.noVat ? null : (
        <TextInput
          label={t('admin.dict.f.percent')}
          required
          value={draft.percent}
          maxLength={6}
          rightSection="%"
          error={draft.percent && !pctValid(draft.percent) ? t('admin.dict.pctError') : null}
          onChange={(e) => set({ percent: e.currentTarget.value })}
        />
      )}
      <Checkbox
        mt="xs"
        label={t('admin.dict.f.isDefault')}
        description={t('admin.dict.f.isDefaultHint')}
        checked={draft.isDefault}
        disabled={record?.is_default === true}
        onChange={(e) => set({ isDefault: e.currentTarget.checked })}
      />
    </>
  );
}

const vat: DictConfig<VatRate, VatDraft> = {
  kind: 'vat-rates',
  load: () => typed<{ items: VatRate[] }>(call(() => api.GET('/admin/vat-rates', all))),
  keyOf: (r) => r.id,
  nameOf: (r) => r.name,
  headers: ['admin.dict.f.name', 'admin.dict.f.percent', 'admin.dict.f.isDefaultShort'],
  cells: (r) => [r.name, r.percent === null ? '—' : `${r.percent}%`, r.is_default ? '✓' : ''],
  empty: { name: '', percent: '', isDefault: false, noVat: false },
  toDraft: (r) => ({ name: r.name, percent: r.percent ?? '', isDefault: r.is_default, noVat: r.percent === null }),
  valid: (d) => d.name.trim() !== '' && (d.noVat || pctValid(d.percent)),
  Fields: VatFields,
  save: (d, r) => {
    const body = {
      name: d.name.trim(),
      percent: d.noVat ? null : dec(d.percent),
      is_default: d.isDefault,
      is_active: d.is_active,
    };
    return typed<VatRate>(
      call(() =>
        r ? api.PATCH('/admin/vat-rates/{id}', { ...byId(r.id), body }) : api.POST('/admin/vat-rates', { body }),
      ),
    );
  },
  remove: (r) => call(() => api.DELETE('/admin/vat-rates/{id}', byId(r.id))),
  locks: vatLocks,
};

// --- Причины проигрыша --------------------------------------------------------------------------

type ReasonDraft = { name: string; other: boolean };

function ReasonFields({ draft, set }: { draft: ReasonDraft; set: (p: Partial<ReasonDraft>) => void }) {
  const { t } = useTranslation();
  return (
    <>
      <Name value={draft.name} max={100} set={(v) => set({ name: v })} />
      <Checkbox
        mt="xs"
        label={t('admin.dict.f.isOther')}
        description={t('admin.dict.f.isOtherHint')}
        checked={draft.other}
        onChange={(e) => set({ other: e.currentTarget.checked })}
      />
    </>
  );
}

const reasons: DictConfig<LossReason, ReasonDraft> = {
  kind: 'loss-reasons',
  load: () => call(() => api.GET('/admin/loss-reasons', all)),
  keyOf: (r) => r.id,
  nameOf: (r) => r.name,
  headers: ['admin.dict.f.name', 'admin.dict.f.isOtherShort'],
  cells: (r) => [r.name, r.is_other ? '✓' : ''],
  empty: { name: '', other: false },
  toDraft: (r) => ({ name: r.name, other: r.is_other }),
  valid: (d) => d.name.trim() !== '',
  Fields: ReasonFields,
  save: (d, r) => {
    const body = { name: d.name.trim(), is_other: d.other, is_active: d.is_active };
    return call(() =>
      r ? api.PATCH('/admin/loss-reasons/{id}', { ...byId(r.id), body }) : api.POST('/admin/loss-reasons', { body }),
    );
  },
  remove: (r) => call(() => api.DELETE('/admin/loss-reasons/{id}', byId(r.id))),
};

// --- Экраны -------------------------------------------------------------------------------------

export const PhasesDict = () => <Dictionary config={phases} />;
export const DisciplinesDict = () => <Dictionary config={disciplines} />;
export const NodeTypesDict = () => <Dictionary config={nodeTypes} />;
export const TagsDict = () => <Dictionary config={tags} />;
export const CurrenciesDict = () => <Dictionary config={currencies} />;
export const ReasonsDict = () => <Dictionary config={reasons} />;

export function ProfilesDict() {
  const lk = useLookups();
  return <Dictionary config={profilesConfig(lk)} />;
}

export function RatiosDict() {
  const lk = useLookups();
  return <Dictionary config={ratiosConfig(lk)} />;
}

export const VatDict = () => <Dictionary config={vat} />;
