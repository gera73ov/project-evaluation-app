/**
 * FE-013 · блок «Команда» настроек проекта (SPEC 11.6 №4–6, №12, №16; FR-PRJ-04, FR-ADM-05,
 * FR-AUTH-AD-10, BR-ROLE-07; DESIGN.md 10.5).
 *
 * Состав меняется целиком `PUT /projects/{id}/members` (контракт: «полный состав команды»):
 * убрать участника, отметить ревьюера. Последнего модератора убрать нельзя (кнопка неактивна,
 * сервер ответит LAST_MODERATOR). «+ Добавить дисциплину» — `POST /projects/{id}/disciplines`.
 * «Найти в AD» — только с правом `project.ad_search` (режим AD). Выбор человека из пользователей
 * приложения для «+ добавить» и «Заменить» ждёт решения по поиску людей (CR), до него кнопок нет.
 */
import { Button, Checkbox, Group, Menu, Modal, Select, TextInput } from '@mantine/core';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { api, type components } from '../../../shared/api/client';
import { call } from '../../../shared/api/problem';
import { ErrorText } from '../../../shared/ui/ErrorText';
import { projectKey, type Project } from '../useProject';

export type Member = components['schemas']['Member'];
type MemberPut = components['schemas']['MembersPut']['members'][number];

export const membersKey = (id: string) => ['members', id] as const;

export function toPut(members: readonly Member[]): MemberPut[] {
  return members.map((m) => ({
    user_id: m.user.id,
    role: m.role,
    discipline_id: m.discipline_id,
    is_reviewer: m.is_reviewer,
  }));
}

function sameSlot(a: Member, b: Member): boolean {
  return a.user.id === b.user.id && a.role === b.role && a.discipline_id === b.discipline_id;
}

function MemberChip({
  member,
  canEdit,
  removable,
  removeHint,
  onRemove,
  onToggleReviewer,
}: {
  member: Member;
  canEdit: boolean;
  removable: boolean;
  removeHint?: string | undefined;
  onRemove: () => void;
  onToggleReviewer?: (() => void) | undefined;
}) {
  const { t } = useTranslation();
  const blocked = member.status === 'blocked';
  const className = `person${member.is_reviewer ? ' reviewer' : ''}${blocked ? ' blocked' : ''}`;
  const label = (
    <>
      <span className="av sm" aria-hidden="true">
        {member.user.initials}
      </span>
      {member.user.full_name}
      {member.is_reviewer ? (
        <span>
          {' '}
          <span aria-hidden="true">★</span> {t('settings.team.reviewer')}
        </span>
      ) : null}
      {blocked ? <span> · {t('settings.team.blocked')}</span> : null}
    </>
  );
  return (
    <span className={className}>
      {canEdit && onToggleReviewer ? (
        <Menu position="bottom-start">
          <Menu.Target>
            <button type="button" className="person-name">
              {label}
            </button>
          </Menu.Target>
          <Menu.Dropdown>
            <Menu.Item onClick={onToggleReviewer}>
              {member.is_reviewer ? t('settings.team.unmakeReviewer') : t('settings.team.makeReviewer')}
            </Menu.Item>
          </Menu.Dropdown>
        </Menu>
      ) : (
        <span className="person-name">{label}</span>
      )}
      {canEdit ? (
        <button
          type="button"
          className="person-x"
          aria-label={t('settings.team.remove', { name: member.user.full_name })}
          title={removable ? undefined : removeHint}
          disabled={!removable}
          onClick={onRemove}
        >
          ×
        </button>
      ) : null}
    </span>
  );
}

export function TeamSection({ project, readOnly }: { project: Project; readOnly: boolean }) {
  const { t } = useTranslation();
  const client = useQueryClient();
  const canEdit = !readOnly && project.my_permissions.includes('team.write');
  const canAddDiscipline = !readOnly && project.my_permissions.includes('project.disciplines.add');
  const canAd = !readOnly && project.my_permissions.includes('project.ad_search');
  const [addOpen, setAddOpen] = useState(false);
  const [adOpen, setAdOpen] = useState(false);

  const members = useQuery({
    queryKey: membersKey(project.id),
    queryFn: () => call(() => api.GET('/projects/{id}/members', { params: { path: { id: project.id } } })),
    select: (data) => data.items as Member[],
  });

  const put = useMutation({
    mutationFn: (next: Member[]) =>
      call(() =>
        api.PUT('/projects/{id}/members', {
          params: { path: { id: project.id } },
          body: { members: toPut(next) },
        }),
      ),
    onSuccess: (data) => {
      client.setQueryData(membersKey(project.id), data);
      void client.invalidateQueries({ queryKey: projectKey(project.id) });
    },
  });

  const list = members.data ?? [];
  const moderators = list.filter((m) => m.role === 'moderator');
  const presale = list.filter((m) => m.role === 'presale');
  const lastModerator = moderators.length <= 1;

  function remove(member: Member) {
    put.mutate(list.filter((m) => !sameSlot(m, member)));
  }
  function toggleReviewer(member: Member) {
    put.mutate(list.map((m) => (sameSlot(m, member) ? { ...m, is_reviewer: !m.is_reviewer } : m)));
  }

  return (
    <section className="sec set-sec" aria-labelledby="set-team">
      <div className="sec-head">
        <h3 id="set-team">{t('settings.team.title')}</h3>
        <span className="sp" />
        {canAd ? (
          <button type="button" className="link" onClick={() => setAdOpen(true)}>
            <span aria-hidden="true">🔍 </span>
            {t('settings.team.adSearch')}
          </button>
        ) : null}
        {canAddDiscipline ? (
          <button type="button" className="link" onClick={() => setAddOpen(true)}>
            {t('settings.team.addDiscipline')}
          </button>
        ) : null}
      </div>
      <ErrorText error={members.error ?? put.error} />

      <div className="set-row">
        <div className="set-label">{t('settings.team.moderators')}</div>
        <div className="chips">
          {moderators.map((m) => (
            <MemberChip
              key={m.user.id}
              member={m}
              canEdit={canEdit}
              removable={!lastModerator}
              removeHint={t('settings.team.lastModerator')}
              onRemove={() => remove(m)}
            />
          ))}
        </div>
      </div>
      <div className="set-row">
        <div className="set-label">{t('settings.team.presale')}</div>
        <div className="chips">
          {presale.length === 0 ? <span className="faint">{t('common.empty')}</span> : null}
          {presale.map((m) => (
            <MemberChip key={m.user.id} member={m} canEdit={canEdit} removable onRemove={() => remove(m)} />
          ))}
        </div>
      </div>

      <table className="t team-table">
        <thead>
          <tr>
            <th>{t('settings.team.discipline')}</th>
            <th>
              {t('settings.team.experts')} <span className="th-hint">{t('settings.team.expertsHint')}</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {project.disciplines.map((discipline) => {
            const experts = list.filter((m) => m.role === 'expert' && m.discipline_id === discipline.discipline_id);
            return (
              <tr key={discipline.discipline_id}>
                <td>{discipline.name}</td>
                <td>
                  <div className="chips">
                    {experts.length === 0 ? (
                      <span className="pill warn">
                        <span aria-hidden="true">⚠</span> {t('settings.team.noExpert')}
                      </span>
                    ) : null}
                    {experts.map((m) => (
                      <MemberChip
                        key={m.user.id}
                        member={m}
                        canEdit={canEdit}
                        removable
                        onRemove={() => remove(m)}
                        onToggleReviewer={() => toggleReviewer(m)}
                      />
                    ))}
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      {addOpen ? <AddDisciplineDialog project={project} onClose={() => setAddOpen(false)} /> : null}
      {adOpen ? <AdSearchDialog project={project} onClose={() => setAdOpen(false)} /> : null}
    </section>
  );
}

function AddDisciplineDialog({ project, onClose }: { project: Project; onClose: () => void }) {
  const { t } = useTranslation();
  const client = useQueryClient();
  const [choice, setChoice] = useState<string | null>(null);
  const dict = useQuery({
    queryKey: ['dict', 'disciplines'],
    queryFn: () => call(() => api.GET('/admin/disciplines')),
    staleTime: 10 * 60_000,
  });
  const taken = new Set(project.disciplines.map((d) => d.discipline_id));
  const options = (dict.data?.items ?? [])
    .filter((d) => d.is_active && !taken.has(d.id))
    .map((d) => ({ value: d.id, label: d.name }));
  const add = useMutation({
    mutationFn: (disciplineId: string) =>
      call(() =>
        api.POST('/projects/{id}/disciplines', {
          params: { path: { id: project.id } },
          body: { discipline_id: disciplineId },
        }),
      ),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: projectKey(project.id) });
      void client.invalidateQueries({ queryKey: ['tree', project.id] });
      onClose();
    },
  });
  return (
    <Modal opened onClose={onClose} title={t('settings.team.addDisciplineTitle')} centered>
      <ErrorText error={add.error} />
      <Select
        label={t('settings.team.discipline')}
        data={options}
        value={choice}
        onChange={setChoice}
        searchable
        mb="xs"
        data-autofocus
      />
      <p className="set-hint">{t('settings.team.addDisciplineHint')}</p>
      <Group justify="flex-end">
        <Button variant="default" onClick={onClose}>
          {t('common.cancel')}
        </Button>
        <Button disabled={!choice} loading={add.isPending} onClick={() => choice && add.mutate(choice)}>
          {t('settings.team.addDisciplineTitle')}
        </Button>
      </Group>
    </Modal>
  );
}

/** «Найти в AD» (11.6 №16, FR-AUTH-AD-10): поиск по каталогу и назначение экспертом дисциплины. */
function AdSearchDialog({ project, onClose }: { project: Project; onClose: () => void }) {
  const { t } = useTranslation();
  const client = useQueryClient();
  const [q, setQ] = useState('');
  const [submitted, setSubmitted] = useState('');
  const [picked, setPicked] = useState<string | null>(null);
  const [discipline, setDiscipline] = useState<string | null>(project.disciplines[0]?.discipline_id ?? null);
  const [reviewer, setReviewer] = useState(false);
  const search = useQuery({
    queryKey: ['ad-search', project.id, submitted],
    queryFn: () =>
      call(() => api.GET('/projects/{id}/ad-search', { params: { path: { id: project.id }, query: { q: submitted } } })),
    enabled: submitted.length >= 2,
  });
  const create = useMutation({
    mutationFn: () =>
      call(() =>
        api.POST('/projects/{id}/ad-search', {
          params: { path: { id: project.id } },
          body: { object_guid: picked ?? '', discipline_id: discipline ?? '', is_reviewer: reviewer },
        }),
      ),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: membersKey(project.id) });
      void client.invalidateQueries({ queryKey: projectKey(project.id) });
      onClose();
    },
  });
  const items = search.data?.items ?? [];
  return (
    <Modal opened onClose={onClose} title={t('settings.team.adTitle')} centered size="lg">
      <form
        className="set-inline"
        onSubmit={(e) => {
          e.preventDefault();
          setSubmitted(q.trim());
        }}
      >
        <TextInput
          className="grow"
          aria-label={t('settings.team.adQuery')}
          placeholder={t('settings.team.adQuery')}
          value={q}
          onChange={(e) => setQ(e.currentTarget.value)}
          data-autofocus
        />
        <Button type="submit" variant="default" disabled={q.trim().length < 2}>
          {t('settings.team.adFind')}
        </Button>
      </form>
      <ErrorText error={search.error ?? create.error} />
      {search.isSuccess && items.length === 0 ? <p className="set-hint">{t('settings.team.adEmpty')}</p> : null}
      <ul className="ad-list">
        {items.map((item) => (
          <li key={item.object_guid}>
            <label>
              <input
                type="radio"
                name="ad-user"
                value={item.object_guid}
                disabled={!item.in_access_group}
                checked={picked === item.object_guid}
                onChange={() => setPicked(item.object_guid)}
              />
              <span>
                <b>{item.full_name}</b> · {item.login}
                {item.department ? ` · ${item.department}` : ''}
                {!item.in_access_group ? <span className="faint"> · {t('settings.team.adNotInGroup')}</span> : null}
              </span>
            </label>
          </li>
        ))}
      </ul>
      <Group align="end" mt="md">
        <Select
          label={t('settings.team.adDiscipline')}
          data={project.disciplines.map((d) => ({ value: d.discipline_id, label: d.name }))}
          value={discipline}
          onChange={setDiscipline}
          allowDeselect={false}
        />
        <Checkbox
          label={t('settings.team.adReviewer')}
          checked={reviewer}
          onChange={(e) => setReviewer(e.currentTarget.checked)}
          mb={8}
        />
        <span className="sp" />
        <Button disabled={!picked || !discipline} loading={create.isPending} onClick={() => create.mutate()}>
          {t('settings.team.adAdd')}
        </Button>
      </Group>
    </Modal>
  );
}
