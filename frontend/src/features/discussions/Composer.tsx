/**
 * FE-030 · поле ответа в обсуждении (FR-DISC-02…05; 11.4 №14): текст, `@` с автодополнением
 * (дисциплина, участник, «модератор», «заказчик»), флаг «нужен ответ», «📎» — ссылка на документ
 * заказчика (вложений нет, FR-DOC-01), «Отправить» и Ctrl+Enter, «Решено ▾».
 */
import { Menu } from '@mantine/core';
import { useQuery } from '@tanstack/react-query';
import { useRef, useState, type KeyboardEvent } from 'react';
import { useTranslation } from 'react-i18next';

import { api } from '../../shared/api/client';
import { call } from '../../shared/api/problem';
import { keptAddressees, mentionAt, type Addressee } from './feed';

const MAX = 4000;

export interface SendRequest {
  body: string;
  needsAnswer: boolean;
  addressees: Addressee[];
}

export function Composer({
  projectId,
  busy,
  target,
  canResolve,
  canConclude,
  onSend,
  onResolve,
}: {
  projectId: string;
  busy: boolean;
  /** Ответ идёт в вопрос; null — в ленту узла. */
  target: { label: string; onClear: () => void } | null;
  canResolve: boolean;
  /** «Решено» с выводом в комментарий — только у листа. */
  canConclude: boolean;
  onSend: (request: SendRequest) => Promise<boolean>;
  onResolve: (withConclusion: boolean) => void;
}) {
  const { t } = useTranslation();
  const [text, setText] = useState('');
  const [needsAnswer, setNeedsAnswer] = useState(false);
  const [picked, setPicked] = useState<{ addressee: Addressee; label: string }[]>([]);
  const [mention, setMention] = useState<{ query: string; from: number } | null>(null);
  const [active, setActive] = useState(0);
  const [docsOpen, setDocsOpen] = useState(false);
  const area = useRef<HTMLTextAreaElement>(null);

  const suggest = useQuery({
    queryKey: ['suggest', projectId, mention?.query ?? ''],
    queryFn: () =>
      call(() =>
        api.GET('/projects/{id}/members/suggest', {
          params: { path: { id: projectId }, query: { q: mention?.query ?? '' } },
        }),
      ),
    enabled: mention !== null,
    staleTime: 60_000,
  });
  const options = mention ? (suggest.data?.items ?? []) : [];
  const docs = useQuery({
    queryKey: ['documents', projectId],
    queryFn: () => call(() => api.GET('/projects/{id}/documents', { params: { path: { id: projectId } } })),
    enabled: docsOpen,
  });

  const update = (value: string, caret: number) => {
    setText(value);
    setMention(mentionAt(value, caret));
    setActive(0);
  };

  const insert = (piece: string, from: number, to: number) => {
    const next = text.slice(0, from) + piece + text.slice(to);
    setText(next.slice(0, MAX));
    setMention(null);
    requestAnimationFrame(() => {
      const el = area.current;
      if (!el) return;
      el.focus();
      const at = Math.min(from + piece.length, el.value.length);
      el.setSelectionRange(at, at);
    });
  };

  const choose = (index: number) => {
    const option = options.at(index);
    if (!option || !mention) return;
    const caret = area.current?.selectionStart ?? text.length;
    setPicked((prev) => [
      ...prev,
      { addressee: { target_type: option.target_type, target_id: option.target_id }, label: option.label },
    ]);
    insert(`@${option.label} `, mention.from, caret);
  };

  const send = async () => {
    const body = text.trim();
    if (!body || busy) return;
    const ok = await onSend({ body, needsAnswer, addressees: keptAddressees(body, picked) });
    if (ok) {
      setText('');
      setPicked([]);
      setNeedsAnswer(false);
      setMention(null);
    }
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (options.length) {
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        const step = e.key === 'ArrowDown' ? 1 : -1;
        setActive((i) => (i + step + options.length) % options.length);
        return;
      }
      if ((e.key === 'Enter' && !e.ctrlKey && !e.metaKey) || e.key === 'Tab') {
        e.preventDefault();
        choose(active);
        return;
      }
      if (e.key === 'Escape') {
        e.preventDefault();
        setMention(null);
        return;
      }
    }
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      void send();
    }
  };

  const listId = `mention-${projectId}`;
  return (
    <div className="disc-compose">
      {target ? (
        <div className="disc-target">
          {t('discussion.replyTo', { name: target.label })}
          <button type="button" className="link" onClick={target.onClear} aria-label={t('discussion.replyToClear')}>
            ✕
          </button>
        </div>
      ) : null}
      <div className="disc-row">
        <div className="disc-input">
          <textarea
            ref={area}
            rows={1}
            value={text}
            maxLength={MAX}
            placeholder={t('discussion.placeholder')}
            aria-label={t('discussion.input')}
            role="combobox"
            aria-expanded={options.length > 0}
            aria-controls={listId}
            aria-autocomplete="list"
            {...(options.length ? { 'aria-activedescendant': `${listId}-${active}` } : {})}
            onChange={(e) => update(e.currentTarget.value, e.currentTarget.selectionStart)}
            onKeyDown={onKeyDown}
            onBlur={() => setTimeout(() => setMention(null), 150)}
          />
          {options.length ? (
            <ul className="mention-list" id={listId} role="listbox" aria-label={t('discussion.addressees')}>
              {options.map((option, i) => (
                <li
                  key={`${option.target_type}/${option.target_id ?? ''}`}
                  id={`${listId}-${i}`}
                  role="option"
                  aria-selected={i === active}
                  className={i === active ? 'on' : undefined}
                  onMouseDown={(e) => {
                    e.preventDefault();
                    choose(i);
                  }}
                >
                  @{option.label}
                  <span className="mention-kind">{t(`discussion.target.${option.target_type}`)}</span>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
        <Menu opened={docsOpen} onChange={setDocsOpen} width={280} position="top-end" withinPortal>
          <Menu.Target>
            <button
              type="button"
              className="btn-sm ghost"
              aria-label={t('discussion.attach')}
              title={t('discussion.attach')}
            >
              📎
            </button>
          </Menu.Target>
          <Menu.Dropdown>
            <Menu.Label>{t('discussion.attachHint')}</Menu.Label>
            {(docs.data?.items ?? []).filter((d) => d.scan_status === 'clean').length ? (
              (docs.data?.items ?? [])
                .filter((d) => d.scan_status === 'clean')
                .map((doc) => (
                  <Menu.Item
                    key={doc.id}
                    onClick={() => {
                      const link = `${window.location.origin}/projects/${projectId}/settings/documents#${doc.id}`;
                      const caret = area.current?.selectionStart ?? text.length;
                      const space = caret > 0 && !/\s/.test(text.charAt(caret - 1)) ? ' ' : '';
                      insert(`${space}${doc.file_name}: ${link} `, caret, caret);
                    }}
                  >
                    {doc.file_name}
                  </Menu.Item>
                ))
            ) : (
              <Menu.Item disabled>{docs.isPending ? t('common.loading') : t('discussion.noDocs')}</Menu.Item>
            )}
          </Menu.Dropdown>
        </Menu>
        <label className="disc-flag">
          <input type="checkbox" checked={needsAnswer} onChange={(e) => setNeedsAnswer(e.currentTarget.checked)} />
          {t('discussion.needsAnswer')}
        </label>
        <button type="button" className="btn-sm primary" disabled={busy || !text.trim()} onClick={() => void send()}>
          {t('discussion.send')}
        </button>
        {canResolve ? (
          <Menu width={260} position="top-end" withinPortal>
            <Menu.Target>
              <button type="button" className="btn-sm" disabled={busy}>
                {t('discussion.resolve')} ▾
              </button>
            </Menu.Target>
            <Menu.Dropdown>
              <Menu.Item onClick={() => onResolve(false)}>{t('discussion.resolveOnly')}</Menu.Item>
              <Menu.Item
                disabled={!canConclude}
                rightSection={canConclude ? null : <span className="menu-why">{t('discussion.leafOnly')}</span>}
                onClick={() => onResolve(true)}
              >
                {t('discussion.resolveConclude')}
              </Menu.Item>
            </Menu.Dropdown>
          </Menu>
        ) : null}
      </div>
    </div>
  );
}
