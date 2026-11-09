/**
 * FE-031 · закрытые заметки под строкой (FR-NOTE-01, 11.4 №18, FR-2FA-05; DESIGN.md 7.4, 8).
 *
 * Вкладка «🔒 Заметки» видна только с правом `notes.read` (модератор, пресейл, руководитель
 * пресейла); у эксперта её нет в DOM, сервер ему заметки не отдаёт. Пишут и правят свои заметки
 * с `notes.write` (модератор и пресейл); руководитель пресейла только читает. Без пройденного в
 * сессии TOTP сервер отвечает 403 `TOTP_REQUIRED` — вместо списка «🔒 Подтвердите вход кодом».
 */
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { useNavigate } from '../../app/router';
import { useSession } from '../../app/session';
import { api, type components } from '../../shared/api/client';
import { call, errorMessage } from '../../shared/api/problem';
import { formatDateTime } from '../../shared/format/date';
import { AutoLinkText } from '../../shared/ui/AutoLinkText';
import { MoneyGuard, isTotpRequired } from '../../shared/ui/MoneyGuard';

type Note = components['schemas']['Note'];

export const notesKey = (projectId: string, nodeId: string | null) => ['notes', projectId, nodeId] as const;

/** Заметки узла (или проекта при `nodeId = null`); общий запрос для счётчика вкладки и списка. */
export function useNotes(projectId: string, nodeId: string | null, enabled: boolean) {
  return useQuery({
    queryKey: notesKey(projectId, nodeId),
    queryFn: () =>
      call(() =>
        api.GET('/projects/{id}/notes', {
          params: { path: { id: projectId }, query: { limit: 100, ...(nodeId ? { node_id: nodeId } : {}) } },
        }),
      ),
    enabled,
    retry: false,
  });
}

export function NotesPanel({
  projectId,
  nodeId,
  canWrite,
  roleOf,
}: {
  projectId: string;
  nodeId: string | null;
  canWrite: boolean;
  roleOf: (userId: string) => string | null;
}) {
  const { t } = useTranslation();
  const client = useQueryClient();
  const navigate = useNavigate();
  const { session } = useSession();
  const timeZone = session.state === 'ready' ? (session.me.timezone ?? undefined) : undefined;
  const me = session.state === 'ready' ? session.me.id : null;
  const totpEnabled = session.state === 'ready' ? session.me.totp_enabled : false;
  const notes = useNotes(projectId, nodeId, true);
  const [text, setText] = useState('');
  const [editing, setEditing] = useState<{ id: string; body: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async (request: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await request();
      await client.invalidateQueries({ queryKey: notesKey(projectId, nodeId) });
      return true;
    } catch (e) {
      setError(errorMessage(e));
      return false;
    } finally {
      setBusy(false);
    }
  };

  const add = () => {
    const body = text.trim();
    if (!body) return;
    void run(() =>
      call(() =>
        api.POST('/projects/{id}/notes', { params: { path: { id: projectId } }, body: { node_id: nodeId, body } }),
      ),
    ).then((ok) => ok && setText(''));
  };

  const items = (notes.data?.items ?? []) as Note[];
  return (
    <div className="notes">
      <MoneyGuard
        error={notes.error}
        totpEnabled={totpEnabled}
        onUnlocked={() => void notes.refetch()}
        onEnroll={() => navigate('/profile')}
        enrollText={t('notes.enroll')}
      >
        {notes.error && !isTotpRequired(notes.error) ? (
          <div className="err" role="alert">
            {errorMessage(notes.error)}
          </div>
        ) : null}
        {notes.isSuccess && !items.length ? <div className="disc-empty">{t('notes.empty')}</div> : null}
        {items.length ? (
          <ol className="disc-feed notes-feed">
            {items.map((note) => {
              const role = roleOf(note.author.id);
              return (
                <li key={note.id} className="msg note">
                  <span className="msg-ava note-ava" aria-hidden="true">
                    {note.author.initials}
                  </span>
                  <div className="msg-main">
                    <div className="msg-meta">
                      <b>{note.author.full_name}</b>
                      {role ? <span className="msg-role"> ({role})</span> : null}
                      <span> · {formatDateTime(note.created_at, timeZone, true)}</span>
                      {note.edited_at ? <span className="msg-edited"> · {t('discussion.edited')}</span> : null}
                      {canWrite && note.author.id === me && editing?.id !== note.id ? (
                        <span className="msg-acts">
                          <button
                            type="button"
                            className="link"
                            onClick={() => setEditing({ id: note.id, body: note.body })}
                          >
                            {t('discussion.edit')}
                          </button>
                        </span>
                      ) : null}
                    </div>
                    {editing?.id === note.id ? (
                      <div className="msg-edit">
                        <textarea
                          className="note-input"
                          aria-label={t('notes.editLabel')}
                          maxLength={4000}
                          value={editing.body}
                          onChange={(e) => setEditing({ id: note.id, body: e.currentTarget.value })}
                        />
                        <button
                          type="button"
                          className="btn-sm money"
                          disabled={busy || !editing.body.trim()}
                          onClick={() =>
                            void run(() =>
                              call(() =>
                                api.PATCH('/notes/{id}', {
                                  params: { path: { id: note.id } },
                                  body: { body: editing.body.trim() },
                                }),
                              ),
                            ).then((ok) => ok && setEditing(null))
                          }
                        >
                          {t('common.save')}
                        </button>
                        <button type="button" className="btn-sm" onClick={() => setEditing(null)}>
                          {t('common.cancel')}
                        </button>
                      </div>
                    ) : (
                      <div className="msg-body note-body">
                        <AutoLinkText text={note.body} />
                      </div>
                    )}
                  </div>
                </li>
              );
            })}
          </ol>
        ) : null}
        {error ? (
          <div className="err" role="alert">
            {error}
          </div>
        ) : null}
        {canWrite && !notes.isError ? (
          <div className="disc-compose disc-row">
            <div className="disc-input">
              <textarea
                rows={1}
                value={text}
                maxLength={4000}
                placeholder={t('notes.placeholder')}
                aria-label={t('notes.input')}
                onChange={(e) => setText(e.currentTarget.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
                    e.preventDefault();
                    add();
                  }
                }}
              />
            </div>
            <button type="button" className="btn-sm money" disabled={busy || !text.trim()} onClick={add}>
              {t('notes.add')}
            </button>
          </div>
        ) : null}
      </MoneyGuard>
    </div>
  );
}
