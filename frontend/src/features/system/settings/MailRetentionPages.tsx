/**
 * FE-062 · «Почта (SMTP)» и «Сроки хранения» (SPEC 11.2 №1, 7.1, NFR-REL-06): почтовый сервер
 * (пароль — только «изменить»), время ежедневной сводки; сроки хранения журнала аудита, логов,
 * корзины, файлов выгрузок, уведомлений и журнала изменений. Сохранения — со step-up.
 */
import { PasswordInput, Select, TextInput } from '@mantine/core';
import { useTranslation } from 'react-i18next';

import { ErrorText } from '../../../shared/ui/ErrorText';
import { SystemLayout } from '../layout/SystemLayout';
import { IntField, SectionForm, useSection } from './SectionForm';
import { intError, isEmail, isTime, secretSet, valueOf } from './settings';

type SmtpSecurity = 'starttls' | 'tls' | 'none';
type SmtpForm = {
  host: string;
  port: number | null;
  security: SmtpSecurity;
  username: string;
  fromAddress: string;
  fromName: string;
  timeout: number | null;
  password: string | null;
  passwordSet: boolean;
};

function smtpForm(values: object): SmtpForm {
  const s = valueOf<{
    host: string | null;
    port: number;
    security: SmtpSecurity;
    username: string | null;
    from_address: string | null;
    from_name: string;
    timeout_seconds: number;
  }>(values, 'smtp.server');
  return {
    host: s.host ?? '',
    port: s.port,
    security: s.security,
    username: s.username ?? '',
    fromAddress: s.from_address ?? '',
    fromName: s.from_name,
    timeout: s.timeout_seconds,
    password: null,
    passwordSet: secretSet(values, 'smtp.password'),
  };
}

function smtpValues(f: SmtpForm): Record<string, unknown> {
  return {
    'smtp.server': {
      host: f.host.trim() || null,
      port: f.port,
      security: f.security,
      username: f.username.trim() || null,
      from_address: f.fromAddress.trim() || null,
      from_name: f.fromName.trim(),
      timeout_seconds: f.timeout,
    },
    ...(f.password !== null ? { 'smtp.password': f.password } : {}),
  };
}

export function smtpErrors(f: SmtpForm): string[] {
  const out: string[] = [];
  if (!f.host.trim()) out.push('host');
  if (intError(f.port, 'smtp.server', 'port')) out.push('port');
  if (intError(f.timeout, 'smtp.server', 'timeout_seconds')) out.push('timeout');
  if (!isEmail(f.fromAddress.trim())) out.push('fromAddress');
  return out;
}

export function SmtpPage() {
  const { t } = useTranslation();
  const smtp = useSection('smtp');
  const digest = useSection('digest');
  return (
    <SystemLayout active="smtp" title={t('system.menu.smtp')} subtitle={t('system.smtp.subtitle')}>
      <ErrorText error={smtp.error ?? digest.error} />
      {smtp.data ? (
        <SectionForm
          section="smtp"
          title={t('system.smtp.title')}
          data={smtp.data}
          toForm={smtpForm}
          toValues={smtpValues}
          errors={smtpErrors}
          hint={t('system.smtp.hint')}
        >
          {(f, set, shown) => (
            <div className="set-groups">
              <div className="set-grid">
                <TextInput
                  label={t('system.smtp.host')}
                  value={f.host}
                  maxLength={255}
                  error={shown('host') ? t('system.settings.required') : null}
                  onChange={(e) => set({ host: e.currentTarget.value })}
                />
                <IntField
                  label={t('system.smtp.port')}
                  value={f.port}
                  onChange={(v) => set({ port: v })}
                  settingKey="smtp.server"
                  field="port"
                  invalid={shown('port')}
                />
                <Select
                  label={t('system.smtp.security')}
                  allowDeselect={false}
                  value={f.security}
                  data={(['starttls', 'tls', 'none'] as const).map((v) => ({
                    value: v,
                    label: t(`system.smtp.sec.${v}`),
                  }))}
                  onChange={(v) => set({ security: v === 'tls' ? 'tls' : v === 'none' ? 'none' : 'starttls' })}
                />
              </div>
              {f.security === 'none' ? (
                <p className="set-danger" role="alert">
                  {t('system.smtp.noTls')}
                </p>
              ) : null}
              <div className="set-grid">
                <TextInput
                  label={t('system.smtp.username')}
                  value={f.username}
                  maxLength={254}
                  autoComplete="off"
                  onChange={(e) => set({ username: e.currentTarget.value })}
                />
                {f.password === null && f.passwordSet ? (
                  <div>
                    <span className="auth-label">{t('system.smtp.password')}</span>
                    <div className="auth-secret">
                      <span aria-label={t('system.auth.conn.passwordSet')}>••••••</span>
                      <button type="button" className="btn-link" onClick={() => set({ password: '' })}>
                        {t('system.auth.conn.change')}
                      </button>
                    </div>
                  </div>
                ) : (
                  <PasswordInput
                    label={t('system.smtp.password')}
                    value={f.password ?? ''}
                    maxLength={512}
                    autoComplete="new-password"
                    onChange={(e) => set({ password: e.currentTarget.value })}
                  />
                )}
                <IntField
                  label={t('system.smtp.timeout')}
                  value={f.timeout}
                  onChange={(v) => set({ timeout: v })}
                  settingKey="smtp.server"
                  field="timeout_seconds"
                  invalid={shown('timeout')}
                />
              </div>
              <div className="set-grid">
                <TextInput
                  label={t('system.smtp.fromAddress')}
                  value={f.fromAddress}
                  maxLength={254}
                  error={shown('fromAddress') ? t('system.settings.emailError') : null}
                  onChange={(e) => set({ fromAddress: e.currentTarget.value })}
                />
                <TextInput
                  label={t('system.smtp.fromName')}
                  value={f.fromName}
                  maxLength={100}
                  onChange={(e) => set({ fromName: e.currentTarget.value })}
                />
              </div>
            </div>
          )}
        </SectionForm>
      ) : null}
      {digest.data ? (
        <SectionForm
          section="digest"
          title={t('system.digest.title')}
          data={digest.data}
          toForm={(v) => ({ time: valueOf<string>(v, 'digest.time') })}
          toValues={(f) => ({ 'digest.time': f.time })}
          errors={(f) => (isTime(f.time) ? [] : ['time'])}
        >
          {(f, set, shown) => (
            <TextInput
              className="set-time"
              label={t('system.digest.time')}
              description={t('system.digest.hint')}
              type="time"
              value={f.time}
              error={shown('time') ? t('system.digest.error') : null}
              onChange={(e) => set({ time: e.currentTarget.value })}
            />
          )}
        </SectionForm>
      ) : null}
    </SystemLayout>
  );
}

export const RETENTION_FIELDS = [
  'audit_months',
  'app_logs_days',
  'trash_days',
  'export_files_hours',
  'notifications_days',
  'change_log_days',
] as const;
type RetentionField = (typeof RETENTION_FIELDS)[number];
type RetentionForm = Record<RetentionField, number | null>;

export function RetentionPage() {
  const { t } = useTranslation();
  const retention = useSection('retention');
  const K = 'retention.periods';
  return (
    <SystemLayout active="retention" title={t('system.menu.retention')} subtitle={t('system.retention.subtitle')}>
      <ErrorText error={retention.error} />
      {retention.data ? (
        <SectionForm
          section="retention"
          title={t('system.retention.title')}
          data={retention.data}
          toForm={(v) => ({ ...valueOf<RetentionForm>(v, K) })}
          toValues={(f) => ({ [K]: f })}
          errors={(f) => RETENTION_FIELDS.filter((k) => intError(new Map(Object.entries(f)).get(k) ?? null, K, k))}
          hint={t('system.settings.stepUpHint')}
        >
          {(f, set, shown) => (
            <div className="set-grid">
              {RETENTION_FIELDS.map((k) => (
                <IntField
                  key={k}
                  label={t(`system.retention.${k}`)}
                  value={new Map(Object.entries(f)).get(k) ?? null}
                  onChange={(v) => set({ [k]: v } as Partial<RetentionForm>)}
                  settingKey={K}
                  field={k}
                  invalid={shown(k)}
                />
              ))}
            </div>
          )}
        </SectionForm>
      ) : null}
    </SystemLayout>
  );
}
