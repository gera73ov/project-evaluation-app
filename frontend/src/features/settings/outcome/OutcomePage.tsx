/**
 * FE-016 · вкладка «Результат пресейла» (SPEC BR-PRJ-05, 11.6 №1; DESIGN.md 10.5).
 *
 * Результат: не известен / выигран / проигран / отменён заказчиком. Заполняют модератор, пресейл
 * проекта и руководитель пресейла (`outcome.write`) в любом статусе; остальные смотрят.
 * - «Сумма договора» — только при «выигран» и только у ролей с деньгами: у эксперта поля нет в
 *   разметке, сервер ему сумму не отдаёт. Правят её те, кто правит результат и видит деньги (CR-015), сохранение требует
 *   TOTP в сессии — на 403 TOTP_REQUIRED открывается ввод кода и запрос повторяется.
 * - «Причина проигрыша» — из справочника администратора, обязательна при «проигран»; при
 *   «Другое» нужен текст до 500 символов.
 */
import { Button, SegmentedControl, Select, TextInput, Textarea } from '@mantine/core';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Link } from '../../../app/router';
import { api, type components } from '../../../shared/api/client';
import { asDecimalString } from '../../../shared/api/decimal';
import { call } from '../../../shared/api/problem';
import { formatNumber } from '../../../shared/format/number';
import { ErrorText } from '../../../shared/ui/ErrorText';
import { isTotpRequired } from '../../../shared/ui/MoneyGuard';
import { StepUpModal } from '../../../shared/ui/StepUpModal';
import { useReadOnlyOffline } from '../../../shared/ws/WsProvider';
import { SettingsTabs } from '../ProjectSettingsPage';
import { useProject } from '../useProject';

type Outcome = components['schemas']['Outcome'];
type ProjectOutcome = components['schemas']['ProjectOutcome'];
type OutcomePut = components['schemas']['ProjectOutcomePut'];
type LossReason = components['schemas']['LossReason'];

export const OUTCOMES: readonly Outcome[] = ['unknown', 'won', 'lost', 'cancelled'];
export const outcomeKey = (id: string) => ['outcome', id] as const;
const TEXT_MAX = 500;

/** Сумма договора: целое ≥ 0 без ограничения разрядности (CR-002), пробелы допустимы; пусто → null. */
export function parseAmount(input: string): string | null | undefined {
  const text = input.replace(/\s/g, '');
  if (text === '') return null;
  if (!/^\d+$/.test(text)) return undefined;
  return text.replace(/^0+(?=\d)/, '');
}

export interface Draft {
  outcome: Outcome;
  reasonId: string | null;
  reasonText: string;
  amount: string;
}

export type DraftErrors = Partial<Record<'reason' | 'text' | 'amount', string>>;

/** Проверки формы до отправки: те же, что у сервера (BR-PRJ-05). Ключи — коды подписей `outcome.errors.*`. */
export function validateDraft(draft: Draft, reasons: readonly LossReason[], withAmount: boolean): DraftErrors {
  const errors: DraftErrors = {};
  if (draft.outcome === 'lost') {
    const reason = reasons.find((r) => r.id === draft.reasonId);
    if (!reason) errors.reason = 'reasonRequired';
    else if (reason.is_other && !draft.reasonText.trim()) errors.text = 'textRequired';
  }
  if (draft.reasonText.length > TEXT_MAX) errors.text = 'textTooLong';
  if (withAmount && draft.outcome === 'won' && parseAmount(draft.amount) === undefined) errors.amount = 'amount';
  return errors;
}

/** Тело PUT: причина — только при «проигран», текст — только при «Другое», сумма — только с `money.read` (CR-015). */
export function outcomeBody(draft: Draft, reasons: readonly LossReason[], moneyWrite: boolean): OutcomePut {
  const reason = draft.outcome === 'lost' ? reasons.find((r) => r.id === draft.reasonId) : undefined;
  const body: OutcomePut = {
    outcome: draft.outcome,
    loss_reason_id: reason?.id ?? null,
    loss_reason_text: reason?.is_other ? draft.reasonText.trim() : null,
  };
  if (moneyWrite) {
    const amount = draft.outcome === 'won' ? (parseAmount(draft.amount) ?? null) : null;
    body.contract_amount = amount === null ? null : asDecimalString(amount);
  }
  return body;
}

function draftOf(data: ProjectOutcome): Draft {
  const amount = data.money?.contract_amount ?? null;
  return {
    outcome: data.outcome,
    reasonId: data.loss_reason_id,
    reasonText: data.loss_reason_text ?? '',
    amount: amount === null ? '' : formatNumber(amount, 0),
  };
}

function OutcomeForm({
  projectId,
  data,
  reasons,
  canWrite,
  money,
  moneyWrite,
}: {
  projectId: string;
  data: ProjectOutcome;
  reasons: readonly LossReason[];
  canWrite: boolean;
  money: boolean;
  moneyWrite: boolean;
}) {
  const { t } = useTranslation();
  const client = useQueryClient();
  const [draft, setDraft] = useState<Draft>(() => draftOf(data));
  const [base, setBase] = useState(data);
  const [shown, setShown] = useState(false);
  const [saved, setSaved] = useState(false);
  const [stepUp, setStepUp] = useState<OutcomePut | null>(null);
  // ответ сервера (своё сохранение или правка коллеги) — показываем его
  if (data !== base) {
    setBase(data);
    setDraft(draftOf(data));
  }

  const put = useMutation({
    mutationFn: (body: OutcomePut) =>
      call(() => api.PUT('/projects/{id}/outcome', { params: { path: { id: projectId } }, body })),
    onSuccess: (next) => {
      client.setQueryData(outcomeKey(projectId), next);
      setSaved(true);
      setShown(false);
    },
    onError: (error, body) => {
      if (isTotpRequired(error)) setStepUp(body);
    },
  });

  const withAmount = money && moneyWrite && canWrite;
  const errors = validateDraft(draft, reasons, withAmount);
  const invalid = Object.keys(errors).length > 0;
  const reason = reasons.find((r) => r.id === draft.reasonId);
  // в списке — активные причины и текущая, даже если администратор её выключил
  const options = reasons
    .filter((r) => r.is_active || r.id === data.loss_reason_id)
    .map((r) => ({ value: r.id, label: r.name }));
  const change = (patch: Partial<Draft>) => {
    setSaved(false);
    setDraft((d) => ({ ...d, ...patch }));
  };
  const save = () => {
    setShown(true);
    if (invalid) return;
    put.mutate(outcomeBody(draft, reasons, withAmount));
  };
  const errorText = (key: keyof DraftErrors) => {
    const code = new Map(Object.entries(errors)).get(key);
    return shown && code ? t(`outcome.errors.${code}`) : null;
  };

  return (
    <div className="outcome-form">
      <div className="set-row">
        <span className="set-label" id="outcome-result">
          {t('outcome.result')}
        </span>
        <div className="set-field">
          <SegmentedControl
            aria-labelledby="outcome-result"
            value={draft.outcome}
            readOnly={!canWrite}
            disabled={!canWrite}
            data={OUTCOMES.map((o) => ({ value: o, label: t(`outcome.value.${o}`) }))}
            onChange={(v) => change({ outcome: v as Outcome })}
          />
        </div>
      </div>

      {/* у ролей без денег поля нет в разметке (BR-PRJ-05, SEC-AUTHZ-04) */}
      {money && draft.outcome === 'won' ? (
        <div className="set-row money-row">
          <label className="set-label" htmlFor="outcome-amount">
            {t('outcome.amount')}
          </label>
          <div className="set-field">
            <TextInput
              id="outcome-amount"
              className="money-input"
              value={draft.amount}
              readOnly={!withAmount}
              inputMode="numeric"
              placeholder={t('outcome.amountEmpty')}
              error={errorText('amount')}
              w={220}
              rightSection={<span aria-hidden="true">🔒</span>}
              onChange={(e) => change({ amount: e.currentTarget.value })}
              onBlur={() => {
                const parsed = parseAmount(draft.amount);
                if (parsed) change({ amount: formatNumber(parsed, 0) });
              }}
            />
            <span className="set-hint">{t(withAmount ? 'outcome.amountHint' : 'outcome.amountReadOnly')}</span>
          </div>
        </div>
      ) : null}

      {draft.outcome === 'lost' ? (
        <div className="set-row">
          <label className="set-label" htmlFor="outcome-reason">
            {t('outcome.reason')}
          </label>
          <div className="set-field">
            <Select
              id="outcome-reason"
              data={options}
              value={draft.reasonId}
              readOnly={!canWrite}
              placeholder={t('outcome.reasonPick')}
              error={errorText('reason')}
              w={260}
              allowDeselect={false}
              comboboxProps={{ withinPortal: false }}
              onChange={(v) => change({ reasonId: v })}
            />
            {reason?.is_other ? (
              <Textarea
                aria-label={t('outcome.reasonText')}
                value={draft.reasonText}
                readOnly={!canWrite}
                placeholder={t('outcome.reasonTextPlaceholder')}
                maxLength={TEXT_MAX}
                autosize
                minRows={2}
                error={errorText('text')}
                inputWrapperOrder={['label', 'input', 'error', 'description']}
                description={t('outcome.reasonTextCount', { count: draft.reasonText.length, max: TEXT_MAX })}
                onChange={(e) => change({ reasonText: e.currentTarget.value })}
              />
            ) : null}
          </div>
        </div>
      ) : null}

      {canWrite ? (
        <div className="set-row">
          <span />
          <div className="set-actions">
            <Button size="xs" loading={put.isPending} disabled={shown && invalid} onClick={save}>
              {t('common.save')}
            </Button>
            {saved && !put.isPending ? (
              <span className="saved" role="status">
                {t('settings.saved')}
              </span>
            ) : null}
          </div>
        </div>
      ) : null}
      {put.error && !isTotpRequired(put.error) ? <ErrorText error={put.error} /> : null}
      <StepUpModal
        opened={stepUp !== null}
        totpOnly
        onClose={() => setStepUp(null)}
        onSuccess={() => {
          const body = stepUp;
          setStepUp(null);
          if (body) put.mutate(body);
        }}
      />
    </div>
  );
}

export function OutcomePage({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const project = useProject(projectId);
  const offline = useReadOnlyOffline();
  const outcome = useQuery({
    queryKey: outcomeKey(projectId),
    queryFn: () => call(() => api.GET('/projects/{id}/outcome', { params: { path: { id: projectId } } })),
    select: (data) => data as ProjectOutcome,
  });
  const reasons = useQuery({
    queryKey: ['dict', 'loss-reasons'],
    queryFn: () => call(() => api.GET('/admin/loss-reasons', { params: { query: { include_inactive: true } } })),
    staleTime: 10 * 60_000,
    select: (data) => data.items as LossReason[],
  });
  const perms = project.data?.my_permissions ?? [];
  const canWrite = perms.includes('outcome.write') && !offline;

  return (
    <div className="settings">
      <div className="crumbs">
        <Link to={`/projects/${projectId}`}>{project.data?.name ?? ''}</Link>
        <span aria-hidden="true"> › </span>
        <h1>{t('settings.title')}</h1>
      </div>
      <SettingsTabs projectId={projectId} active="outcome" />
      <section className="sec set-sec outcome" aria-labelledby="outcome-title">
        <div className="sec-head">
          <h3 id="outcome-title">{t('settings.tabs.outcome')}</h3>
        </div>
        <p className="set-hint">{t('outcome.lead')}</p>
        {project.data && !perms.includes('outcome.write') ? (
          <p className="set-readonly">{t('outcome.readOnly')}</p>
        ) : null}
        <ErrorText error={project.error ?? outcome.error ?? reasons.error} />
        {project.data && outcome.data ? (
          <OutcomeForm
            projectId={projectId}
            data={outcome.data}
            reasons={reasons.data ?? []}
            canWrite={canWrite}
            money={perms.includes('money.read')}
            moneyWrite={perms.includes('money.read')}
          />
        ) : null}
      </section>
    </div>
  );
}
