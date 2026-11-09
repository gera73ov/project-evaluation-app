/**
 * FE-061 · «Перейти на Active Directory…» (FR-AUTH-SW-01, C-13, G-10, SPEC 11.2 №2): экран
 * последствий → отчёт «сопоставлено / неоднозначно / не найдено» (dry run) → решение по каждому
 * неоднозначному → подтверждение паролем и TOTP и сам переход. Обратного перехода в интерфейсе нет.
 */
import { Button, Group, Modal, Radio, Stack } from '@mantine/core';
import { useMutation } from '@tanstack/react-query';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { api, type components } from '../../../shared/api/client';
import { call } from '../../../shared/api/problem';
import { ErrorText } from '../../../shared/ui/ErrorText';
import { StepUpCancelled, useStepUp } from '../layout/useStepUp';

export type SwitchReport = components['schemas']['SwitchReport'];
type Candidate = components['schemas']['SwitchCandidate'];

/** Итог перехода для блока «Способ входа»: отчёт и сколько неоднозначных решено вручную. */
export type SwitchResult = { report: SwitchReport; resolved: number; at: string };

/** Значение радиокнопки «не сопоставлять» (object_guid = null). */
const NONE = 'none';

export function unresolved(report: SwitchReport, decisions: ReadonlyMap<string, string>): number {
  return report.ambiguous.filter((c) => !decisions.has(c.user_id)).length;
}

export function SwitchWizard({
  opened,
  onClose,
  onDone,
}: {
  opened: boolean;
  onClose: () => void;
  onDone: (result: SwitchResult) => void;
}) {
  const { t } = useTranslation();
  const { run, modal } = useStepUp();
  const [report, setReport] = useState<SwitchReport | null>(null);
  const [decisions, setDecisions] = useState<Map<string, string>>(new Map());

  const dryRun = useMutation({
    mutationFn: () => call(() => api.POST('/system/auth/switch-mode', { body: { mode: 'ad', dry_run: true } })),
    onSuccess: (r) => {
      setReport(r);
      setDecisions(new Map());
    },
  });

  const apply = useMutation({
    mutationFn: async () => {
      const list = [...decisions].map(([user_id, guid]) => ({ user_id, object_guid: guid === NONE ? null : guid }));
      if (list.length > 0)
        await run(() => call(() => api.POST('/system/auth/switch-mode/resolve', { body: { decisions: list } })));
      return run(() => call(() => api.POST('/system/auth/switch-mode', { body: { mode: 'ad', dry_run: false } })));
    },
    onSuccess: (r) => {
      onDone({ report: r, resolved: decisions.size, at: new Date().toISOString() });
      close();
    },
  });

  function close() {
    setReport(null);
    setDecisions(new Map());
    dryRun.reset();
    apply.reset();
    onClose();
  }

  const left = report ? unresolved(report, decisions) : 0;
  const applyError = apply.error instanceof StepUpCancelled ? null : apply.error;

  return (
    <>
      <Modal opened={opened} onClose={close} title={t('system.auth.switch.title')} size="lg" centered>
        {report === null ? (
          <Stack gap="sm">
            <p className="sys-sub">{t('system.auth.switch.intro')}</p>
            <ul className="auth-list">
              <li>{t('system.auth.switch.c1')}</li>
              <li>{t('system.auth.switch.c2')}</li>
              <li>{t('system.auth.switch.c3')}</li>
              <li>{t('system.auth.switch.c4')}</li>
            </ul>
            <ErrorText error={dryRun.error} />
            <Group justify="flex-end">
              <Button variant="default" onClick={close}>
                {t('common.cancel')}
              </Button>
              <Button loading={dryRun.isPending} onClick={() => dryRun.mutate()}>
                {t('system.auth.switch.report')}
              </Button>
            </Group>
          </Stack>
        ) : (
          <Stack gap="sm">
            <ReportCounts report={report} />
            {report.ambiguous.length > 0 ? (
              <section aria-label={t('system.auth.switch.ambiguous')}>
                <h3 className="auth-h3">{t('system.auth.switch.ambiguousTitle')}</h3>
                {report.ambiguous.map((c) => (
                  <Radio.Group
                    key={c.user_id}
                    className="auth-amb"
                    label={`${c.full_name} (${c.login})`}
                    value={decisions.get(c.user_id) ?? null}
                    onChange={(v) => setDecisions((d) => new Map(d).set(c.user_id, v))}
                  >
                    <Stack gap={4} mt={4}>
                      {c.ad_candidates.map((a) => (
                        <Radio key={a.object_guid} value={a.object_guid} label={`${a.full_name} · ${a.login}`} />
                      ))}
                      <Radio value={NONE} label={t('system.auth.switch.none')} />
                    </Stack>
                  </Radio.Group>
                ))}
              </section>
            ) : null}
            <CandidateList title={t('system.auth.switch.notFoundTitle')} items={report.not_found} />
            <CandidateList title={t('system.auth.switch.matchedTitle')} items={report.matched} matched />
            <p className="sys-sub">{t('system.auth.switch.confirmHint')}</p>
            <ErrorText error={applyError} />
            <Group justify="flex-end">
              <Button variant="default" onClick={close}>
                {t('common.cancel')}
              </Button>
              <Button color="red" disabled={left > 0} loading={apply.isPending} onClick={() => apply.mutate()}>
                {left > 0 ? t('system.auth.switch.left', { count: left }) : t('system.auth.switch.apply')}
              </Button>
            </Group>
          </Stack>
        )}
      </Modal>
      {modal}
    </>
  );
}

export function ReportCounts({ report, resolved }: { report: SwitchReport; resolved?: number }) {
  const { t } = useTranslation();
  const ambiguous = resolved ?? report.ambiguous.length;
  return (
    <p className="auth-counts">
      {t('system.auth.switch.matched', { count: report.matched.length })} ·{' '}
      {resolved !== undefined
        ? t('system.auth.switch.ambiguousResolved', { count: ambiguous })
        : t('system.auth.switch.ambiguousCount', { count: ambiguous })}{' '}
      · {t('system.auth.switch.notFound', { count: report.not_found.length })}
    </p>
  );
}

function CandidateList({ title, items, matched }: { title: string; items: Candidate[]; matched?: boolean }) {
  const { t } = useTranslation();
  if (items.length === 0) return null;
  return (
    <details className="auth-details" open={!matched}>
      <summary>
        {title} ({items.length})
      </summary>
      {matched ? null : <p className="sys-sub">{t('system.auth.switch.notFoundHint')}</p>}
      <ul className="auth-list">
        {items.map((c) => (
          <li key={c.user_id}>
            {c.full_name} ({c.login}){matched && c.ad_candidates[0] ? ` → ${c.ad_candidates[0].login}` : ''}
          </li>
        ))}
      </ul>
    </details>
  );
}

/** Отчёт после перехода (ссылка «отчёт» в блоке «Способ входа»). */
export function SwitchReportModal({ result, onClose }: { result: SwitchResult | null; onClose: () => void }) {
  const { t } = useTranslation();
  return (
    <Modal opened={result !== null} onClose={onClose} title={t('system.auth.switch.reportTitle')} size="lg" centered>
      {result ? (
        <Stack gap="sm">
          <ReportCounts report={result.report} resolved={result.resolved} />
          <CandidateList title={t('system.auth.switch.notFoundTitle')} items={result.report.not_found} />
          <CandidateList title={t('system.auth.switch.matchedTitle')} items={result.report.matched} matched />
        </Stack>
      ) : null}
    </Modal>
  );
}
