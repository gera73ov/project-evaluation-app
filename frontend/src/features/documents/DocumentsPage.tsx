/**
 * FE-017 · вкладка «Документы заказчика» (SPEC 11.7 №1–6, FR-DOC-01, SEC-WEB-10; DESIGN.md 10.6, 2.5).
 *
 * - Зона загрузки (перетаскивание или выбор): PDF, DOCX, XLSX до 50 МБ — проверяется до отправки,
 *   окончательно решает сервер. Загружают и удаляют модератор и пресейл (`docs.write`).
 * - «Проверяется» — скачать нельзя; «Заражён» — строка висит 24 часа, вместо действий «недоступен».
 * - Статус проверки обновляется по `document.scanned`; пока есть непроверенные файлы, список
 *   дополнительно перечитывается раз в 5 с (на случай потерянного события).
 * - Справа: место проекта из 1 ГБ, «Кто что может», как сослаться на документ в обсуждении.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useRef, useState, type DragEvent } from 'react';
import { useTranslation } from 'react-i18next';

import { Link } from '../../app/router';
import { useSession } from '../../app/session';
import { api, type components } from '../../shared/api/client';
import { call, errorMessage } from '../../shared/api/problem';
import { saveBlob } from '../../shared/api/saveBlob';
import { formatDateTime } from '../../shared/format/date';
import { formatNumber } from '../../shared/format/number';
import { ConfirmDialog } from '../../shared/ui/ConfirmDialog';
import { EmptyState } from '../../shared/ui/EmptyState';
import { ErrorText } from '../../shared/ui/ErrorText';
import { useReadOnlyOffline } from '../../shared/ws/WsProvider';
import { SettingsTabs } from '../settings/ProjectSettingsPage';
import { useProject } from '../settings/useProject';

type Doc = components['schemas']['Document'];
type DocList = components['schemas']['DocumentList'];

export const documentsKey = (projectId: string) => ['documents', projectId] as const;
export const MAX_FILE_BYTES = 50 * 1024 * 1024;
const MB = 1024 * 1024;
const GB = 1024 * MB;
const POLL_MS = 5000;

/** Формат по расширению: значок и проверка до отправки. Макросы (.docm, .xlsm) не принимаются. */
export function fileKind(name: string): 'pdf' | 'docx' | 'xlsx' | null {
  const ext = /\.([a-z0-9]+)$/i.exec(name)?.[1]?.toLowerCase();
  return ext === 'pdf' || ext === 'docx' || ext === 'xlsx' ? ext : null;
}

/** Ошибка выбранного файла до отправки: тип или размер; null — можно загружать. */
export function checkFile(file: { name: string; size: number }): 'type' | 'size' | 'empty' | null {
  if (!fileKind(file.name)) return 'type';
  if (file.size === 0) return 'empty';
  return file.size > MAX_FILE_BYTES ? 'size' : null;
}

/** Размер как на макете: «4,2 МБ», «0,3 МБ», «1 ГБ». */
export function formatSize(bytes: number): string {
  if (bytes >= GB) return `${formatNumber(String(bytes / GB), bytes % GB === 0 ? 0 : 1)} ГБ`;
  return `${formatNumber(String(bytes / MB), 1)} МБ`;
}

/** Ссылка на документ для обсуждений: номер по порядку загрузки, как «#doc-1» на макете; отклонённые без номера. */
export function docLabels(items: readonly Doc[]): Map<string, string> {
  const ordered = items
    .filter((d) => d.scan_status !== 'infected' && d.scan_status !== 'error')
    .sort((a, b) => a.uploaded_at.localeCompare(b.uploaded_at));
  return new Map(ordered.map((d, i) => [d.id, `#doc-${i + 1}`]));
}

function DocIcon({ doc }: { doc: Doc }) {
  const kind = fileKind(doc.file_name);
  const rejected = doc.scan_status === 'infected' || doc.scan_status === 'error';
  return (
    <span className={`doc-ic ${rejected ? 'off' : (kind ?? 'off')}`} aria-hidden="true">
      {(kind ?? '?').toUpperCase()}
    </span>
  );
}

function ScanPill({ status }: { status: Doc['scan_status'] }) {
  const { t } = useTranslation();
  const cls = status === 'clean' ? 'ok' : status === 'pending' ? 'warn' : 'bad';
  return <span className={`pill ${cls}`}>{t(`documents.scan.${status}`)}</span>;
}

async function download(doc: Doc) {
  const blob = await call(() =>
    api.GET('/documents/{id}/download', { params: { path: { id: doc.id } }, parseAs: 'blob' }),
  );
  saveBlob(blob as Blob, doc.file_name);
}

export function DocumentsPage({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const client = useQueryClient();
  // статус проверки — по `document.scanned` (SPEC 11.7 №2)
  const project = useProject(projectId, (event) => {
    if (event.event === 'document.scanned') void client.invalidateQueries({ queryKey: documentsKey(projectId) });
  });
  const offline = useReadOnlyOffline();
  const { session } = useSession();
  const timeZone = session.state === 'ready' ? (session.me.timezone ?? undefined) : undefined;
  const input = useRef<HTMLInputElement>(null);
  const [drag, setDrag] = useState(false);
  const [pickError, setPickError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<unknown>(null);
  const [removing, setRemoving] = useState<Doc | null>(null);
  const [removed, setRemoved] = useState<string | null>(null);

  const docs = useQuery({
    queryKey: documentsKey(projectId),
    queryFn: () => call(() => api.GET('/projects/{id}/documents', { params: { path: { id: projectId } } })),
    select: (data) => data as DocList,
    refetchInterval: (query) =>
      (query.state.data as DocList | undefined)?.items.some((d) => d.scan_status === 'pending') ? POLL_MS : false,
  });

  const upload = useMutation({
    mutationFn: (file: File) =>
      call(() =>
        api.POST('/projects/{id}/documents', {
          params: { path: { id: projectId } },
          body: { file: file as unknown as string },
          bodySerializer: (body) => {
            const form = new FormData();
            form.append('file', body.file as unknown as Blob, (body.file as unknown as File).name);
            return form;
          },
        }),
      ),
    onSuccess: () => client.invalidateQueries({ queryKey: documentsKey(projectId) }),
  });
  const remove = useMutation({
    mutationFn: (doc: Doc) => call(() => api.DELETE('/documents/{id}', { params: { path: { id: doc.id } } })),
    onSuccess: (_data, doc) => {
      setRemoving(null);
      setRemoved(doc.file_name);
      return client.invalidateQueries({ queryKey: documentsKey(projectId) });
    },
    onError: (error) => {
      setRemoving(null);
      setActionError(error);
    },
  });

  const perms = project.data?.my_permissions ?? [];
  const canWrite = perms.includes('docs.write') && !offline;
  const items = docs.data?.items ?? [];
  const labels = docLabels(items);

  const pick = (files: FileList | null) => {
    const file = files?.[0];
    if (!file) return;
    const problem = checkFile(file);
    setRemoved(null);
    setActionError(null);
    if (problem) {
      setPickError(t(`documents.errors.${problem}`));
      return;
    }
    setPickError(null);
    upload.mutate(file);
  };
  const onDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDrag(false);
    if (canWrite) pick(e.dataTransfer.files);
  };

  const used = docs.data?.used_bytes ?? 0;
  const limit = docs.data?.limit_bytes ?? GB;
  const share = Math.min(100, (used / limit) * 100);

  return (
    <div className="settings">
      <div className="crumbs">
        <Link to={`/projects/${projectId}`}>{project.data?.name ?? ''}</Link>
        <span aria-hidden="true"> › </span>
        <h1>{t('settings.title')}</h1>
      </div>
      <SettingsTabs projectId={projectId} active="documents" />
      <div className="docs-grid">
        <section className="docs-main" aria-labelledby="docs-title">
          <h2 id="docs-title" className="sr-only">
            {t('settings.tabs.documents')}
          </h2>
          {canWrite ? (
            <div
              className={drag ? 'dropzone on' : 'dropzone'}
              onDragOver={(e) => {
                e.preventDefault();
                setDrag(true);
              }}
              onDragLeave={() => setDrag(false)}
              onDrop={onDrop}
            >
              <span className="dz-ic" aria-hidden="true">
                ⇪
              </span>
              <div>
                <b>
                  {t('documents.drop')}{' '}
                  <button type="button" className="link" onClick={() => input.current?.click()}>
                    {t('documents.choose')}
                  </button>
                </b>
                <div className="dz-hint">{t('documents.rules')}</div>
              </div>
              <input
                ref={input}
                type="file"
                hidden
                aria-label={t('documents.fileInput')}
                accept=".pdf,.docx,.xlsx"
                onChange={(e) => {
                  pick(e.currentTarget.files);
                  e.currentTarget.value = '';
                }}
              />
            </div>
          ) : null}
          {pickError ? (
            <div className="err" role="alert">
              {pickError}
            </div>
          ) : null}
          {upload.error ? (
            <div className="err" role="alert">
              {errorMessage(upload.error)}
            </div>
          ) : null}
          {actionError ? <ErrorText error={actionError} /> : null}
          {removed ? (
            <div className="res" role="status">
              {t('documents.removed', { name: removed })}
            </div>
          ) : null}
          <ErrorText error={project.error ?? docs.error} />
          {docs.isSuccess && !items.length && !upload.isPending ? <EmptyState title={t('documents.empty')} /> : null}
          {items.length || upload.isPending ? (
            <table className="t docs-table">
              <thead>
                <tr>
                  <th>{t('documents.col.name')}</th>
                  <th>{t('documents.col.by')}</th>
                  <th className="num">{t('documents.col.size')}</th>
                  <th>{t('documents.col.scan')}</th>
                  <th>
                    <span className="sr-only">{t('documents.col.actions')}</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {items.map((doc) => {
                  const rejected = doc.scan_status === 'infected' || doc.scan_status === 'error';
                  return (
                    <tr key={doc.id} id={doc.id} className={rejected ? 'row-error' : undefined}>
                      <td>
                        <div className="doc-name">
                          <DocIcon doc={doc} />
                          <div>
                            <div className={rejected ? 'doc-file off' : 'doc-file'}>{doc.file_name}</div>
                            <div className="doc-sub">
                              {rejected ? (
                                t(`documents.sub.${doc.scan_status}`)
                              ) : doc.scan_status === 'pending' ? (
                                t('documents.sub.pending')
                              ) : (
                                <>
                                  {t('documents.linkFor')} <a href={`#${doc.id}`}>{labels.get(doc.id)}</a>
                                </>
                              )}
                            </div>
                          </div>
                        </div>
                      </td>
                      <td>
                        {doc.uploaded_by.full_name} · {formatDateTime(doc.uploaded_at, timeZone, true)}
                      </td>
                      <td className="num">{formatSize(doc.size_bytes)}</td>
                      <td>
                        <ScanPill status={doc.scan_status} />
                      </td>
                      <td className="doc-acts">
                        {rejected ? (
                          <span className="faint">{t('documents.unavailable')}</span>
                        ) : (
                          <>
                            <button
                              type="button"
                              className="btn-sm"
                              disabled={doc.scan_status !== 'clean'}
                              aria-label={t('documents.download', { name: doc.file_name })}
                              onClick={() => {
                                setActionError(null);
                                download(doc).catch(setActionError);
                              }}
                            >
                              {t('documents.downloadShort')}
                            </button>
                            {canWrite ? (
                              <button
                                type="button"
                                className="btn-sm ghost"
                                aria-label={t('documents.remove', { name: doc.file_name })}
                                title={t('documents.remove', { name: doc.file_name })}
                                onClick={() => setRemoving(doc)}
                              >
                                🗑
                              </button>
                            ) : null}
                          </>
                        )}
                      </td>
                    </tr>
                  );
                })}
                {upload.isPending && upload.variables ? (
                  <tr className="doc-uploading">
                    <td colSpan={5}>
                      <div className="doc-name">
                        <span className={`doc-ic ${fileKind(upload.variables.name) ?? 'off'}`} aria-hidden="true">
                          {(fileKind(upload.variables.name) ?? '?').toUpperCase()}
                        </span>
                        <div>
                          <div className="doc-file">{upload.variables.name}</div>
                          <div className="doc-sub">{t('documents.uploading')}</div>
                        </div>
                      </div>
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          ) : null}
          <p className="docs-note">{t('documents.note')}</p>
        </section>

        <aside className="docs-side">
          <section className="card" aria-labelledby="docs-space">
            <h3 id="docs-space">{t('documents.space.title')}</h3>
            <div
              className="space-bar"
              role="progressbar"
              aria-labelledby="docs-space"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={Math.round(share)}
            >
              <i style={{ width: `${Math.max(share, used ? 2 : 0)}%` }} />
            </div>
            <div className="space-row">
              <span>{t('documents.space.used')}</span>
              <b>{t('documents.space.of', { used: formatSize(used), limit: formatSize(limit) })}</b>
            </div>
          </section>
          <section className="card" aria-labelledby="docs-who">
            <h3 id="docs-who">{t('documents.who.title')}</h3>
            <dl className="who-list">
              <dt>{t('documents.who.writers')}</dt>
              <dd>{t('documents.who.write')}</dd>
              <dt>{t('documents.who.experts')}</dt>
              <dd>{t('documents.who.read')}</dd>
              <dt>{t('documents.who.head')}</dt>
              <dd>{t('documents.who.read')}</dd>
            </dl>
            <p className="card-hint">{t('documents.who.audit')}</p>
          </section>
          <section className="card" aria-labelledby="docs-link">
            <h3 id="docs-link">{t('documents.link.title')}</h3>
            <p className="card-quote">{t('documents.link.example')}</p>
            <p className="card-hint">{t('documents.link.hint')}</p>
          </section>
        </aside>
      </div>
      <ConfirmDialog
        opened={removing !== null}
        title={t('documents.removeTitle')}
        message={t('documents.removeMessage', { name: removing?.file_name ?? '' })}
        confirmLabel={t('documents.removeConfirm')}
        danger
        busy={remove.isPending}
        onConfirm={() => removing && remove.mutate(removing)}
        onCancel={() => setRemoving(null)}
      />
    </div>
  );
}
