/**
 * FE-062 · «Безопасность» (SPEC 11.2 №1, FR-AUTH-LOC-02, FR-SESS-02, FR-LOCK-*, FR-2FA-02,
 * FR-SA-04, SEC-AUD-05): пароли, сессии, блокировки, обязательность TOTP по ролям (красное
 * предупреждение, если отключён обязательный по умолчанию), разрешённые сети админки, адрес ИБ;
 * отдельной карточкой — передача аудита в SIEM. Все сохранения — со step-up.
 */
import { Checkbox, FileButton, Button, Switch, TextInput, Textarea, PasswordInput } from '@mantine/core';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { ErrorText } from '../../../shared/ui/ErrorText';
import { SystemLayout } from '../layout/SystemLayout';
import { MFA_DEFAULT_REQUIRED, mfaWarningRoles, type MfaRole } from '../layout/system';
import { certProblem } from '../auth/auth';
import { IntField, SectionForm, useSection } from './SectionForm';
import { intError, isCidr, isEmail, lines, secretSet, valueOf } from './settings';

type Password = {
  min_length: number | null;
  max_length: number | null;
  check_common_passwords: boolean;
  forbid_personal_data: boolean;
  history: number | null;
  expiry_days: number | null;
  require_uppercase: boolean;
  require_digit: boolean;
  require_special: boolean;
  max_sessions: number | null;
};
type Session = { idle_minutes_user: number | null; idle_minutes_admin: number | null; absolute_hours: number | null };
type Lockout = { max_failures: number | null; lock_minutes: number | null };
type Mfa = Record<MfaRole | 'user', 'optional' | 'required'>;

type SecurityForm = {
  password: Password;
  expiryOn: boolean;
  sessionsOn: boolean;
  session: Session;
  lockout: Lockout;
  mfa: Mfa;
  networks: string;
  alertEmail: string;
};

export const MFA_ROLES = [...MFA_DEFAULT_REQUIRED, 'user'] as const;

function securityForm(values: object): SecurityForm {
  const password = valueOf<Password>(values, 'security.password_policy');
  return {
    password: { ...password, expiry_days: password.expiry_days ?? 90, max_sessions: password.max_sessions ?? 5 },
    expiryOn: password.expiry_days !== null,
    sessionsOn: password.max_sessions !== null,
    session: valueOf<Session>(values, 'security.session'),
    lockout: valueOf<Lockout>(values, 'security.lockout'),
    mfa: valueOf<Mfa>(values, 'security.mfa_policy'),
    networks: (valueOf<string[]>(values, 'security.admin_networks') ?? []).join('\n'),
    alertEmail: valueOf<string | null>(values, 'security.alert_email') ?? '',
  };
}

function securityValues(f: SecurityForm): Record<string, unknown> {
  return {
    'security.password_policy': {
      ...f.password,
      expiry_days: f.expiryOn ? f.password.expiry_days : null,
      max_sessions: f.sessionsOn ? f.password.max_sessions : null,
    },
    'security.session': f.session,
    'security.lockout': f.lockout,
    'security.mfa_policy': f.mfa,
    'security.admin_networks': lines(f.networks),
    'security.alert_email': f.alertEmail.trim() || null,
  };
}

export function securityErrors(f: SecurityForm): string[] {
  const out: string[] = [];
  const P = 'security.password_policy';
  const pw = new Map<string, number | null>([
    ['min_length', f.password.min_length],
    ['max_length', f.password.max_length],
    ['history', f.password.history],
  ]);
  for (const k of ['min_length', 'max_length', 'history'])
    if (intError(pw.get(k) ?? null, P, k)) out.push(`password.${k}`);
  if (f.expiryOn && intError(f.password.expiry_days, P, 'expiry_days')) out.push('password.expiry_days');
  if (f.sessionsOn && intError(f.password.max_sessions, P, 'max_sessions')) out.push('password.max_sessions');
  if ((f.password.min_length ?? 0) > (f.password.max_length ?? 0)) out.push('password.max_length');
  for (const [k, v] of Object.entries(f.session)) if (intError(v, 'security.session', k)) out.push(`session.${k}`);
  for (const [k, v] of Object.entries(f.lockout)) if (intError(v, 'security.lockout', k)) out.push(`lockout.${k}`);
  if (lines(f.networks).some((n) => !isCidr(n))) out.push('networks');
  if (f.alertEmail.trim() && !isEmail(f.alertEmail.trim())) out.push('alertEmail');
  return out;
}

export function SecurityPage() {
  const { t } = useTranslation();
  const security = useSection('security');
  const siem = useSection('siem');
  return (
    <SystemLayout active="security" title={t('system.menu.security')} subtitle={t('system.security.subtitle')}>
      <ErrorText error={security.error ?? siem.error} />
      {security.data ? (
        <SectionForm
          section="security"
          title={t('system.security.title')}
          data={security.data}
          toForm={securityForm}
          toValues={securityValues}
          errors={securityErrors}
          hint={t('system.settings.stepUpHint')}
        >
          {(f, set, shown) => {
            const pw = (patch: Partial<Password>) => set({ password: { ...f.password, ...patch } });
            const P = 'security.password_policy';
            const off = mfaWarningRoles({ 'security.mfa_policy': f.mfa });
            return (
              <div className="set-groups">
                <fieldset className="set-group">
                  <legend>{t('system.security.passwords')}</legend>
                  <div className="set-grid">
                    <IntField
                      label={t('system.security.minLength')}
                      value={f.password.min_length}
                      onChange={(v) => pw({ min_length: v })}
                      settingKey={P}
                      field="min_length"
                      invalid={shown('password.min_length')}
                    />
                    <IntField
                      label={t('system.security.maxLength')}
                      value={f.password.max_length}
                      onChange={(v) => pw({ max_length: v })}
                      settingKey={P}
                      field="max_length"
                      invalid={shown('password.max_length')}
                    />
                    <IntField
                      label={t('system.security.history')}
                      value={f.password.history}
                      onChange={(v) => pw({ history: v })}
                      settingKey={P}
                      field="history"
                      invalid={shown('password.history')}
                    />
                  </div>
                  <div className="set-checks">
                    <Checkbox
                      label={t('system.security.common')}
                      checked={f.password.check_common_passwords}
                      onChange={(e) => pw({ check_common_passwords: e.currentTarget.checked })}
                    />
                    <Checkbox
                      label={t('system.security.personal')}
                      checked={f.password.forbid_personal_data}
                      onChange={(e) => pw({ forbid_personal_data: e.currentTarget.checked })}
                    />
                    <Checkbox
                      label={t('system.security.upper')}
                      checked={f.password.require_uppercase}
                      onChange={(e) => pw({ require_uppercase: e.currentTarget.checked })}
                    />
                    <Checkbox
                      label={t('system.security.digit')}
                      checked={f.password.require_digit}
                      onChange={(e) => pw({ require_digit: e.currentTarget.checked })}
                    />
                    <Checkbox
                      label={t('system.security.special')}
                      checked={f.password.require_special}
                      onChange={(e) => pw({ require_special: e.currentTarget.checked })}
                    />
                  </div>
                  <div className="set-grid">
                    <div>
                      <Checkbox
                        mb={6}
                        label={t('system.security.expiryOn')}
                        checked={f.expiryOn}
                        onChange={(e) => set({ expiryOn: e.currentTarget.checked })}
                      />
                      {f.expiryOn ? (
                        <IntField
                          label={t('system.security.expiry')}
                          value={f.password.expiry_days}
                          onChange={(v) => pw({ expiry_days: v })}
                          settingKey={P}
                          field="expiry_days"
                          invalid={shown('password.expiry_days')}
                        />
                      ) : null}
                    </div>
                    <div>
                      <Checkbox
                        mb={6}
                        label={t('system.security.sessionsOn')}
                        checked={f.sessionsOn}
                        onChange={(e) => set({ sessionsOn: e.currentTarget.checked })}
                      />
                      {f.sessionsOn ? (
                        <IntField
                          label={t('system.security.maxSessions')}
                          value={f.password.max_sessions}
                          onChange={(v) => pw({ max_sessions: v })}
                          settingKey={P}
                          field="max_sessions"
                          invalid={shown('password.max_sessions')}
                        />
                      ) : null}
                    </div>
                  </div>
                </fieldset>

                <fieldset className="set-group">
                  <legend>{t('system.security.sessions')}</legend>
                  <div className="set-grid">
                    <IntField
                      label={t('system.security.idleUser')}
                      value={f.session.idle_minutes_user}
                      onChange={(v) => set({ session: { ...f.session, idle_minutes_user: v } })}
                      settingKey="security.session"
                      field="idle_minutes_user"
                      invalid={shown('session.idle_minutes_user')}
                    />
                    <IntField
                      label={t('system.security.idleAdmin')}
                      value={f.session.idle_minutes_admin}
                      onChange={(v) => set({ session: { ...f.session, idle_minutes_admin: v } })}
                      settingKey="security.session"
                      field="idle_minutes_admin"
                      invalid={shown('session.idle_minutes_admin')}
                    />
                    <IntField
                      label={t('system.security.absolute')}
                      value={f.session.absolute_hours}
                      onChange={(v) => set({ session: { ...f.session, absolute_hours: v } })}
                      settingKey="security.session"
                      field="absolute_hours"
                      invalid={shown('session.absolute_hours')}
                    />
                  </div>
                </fieldset>

                <fieldset className="set-group">
                  <legend>{t('system.security.lockout')}</legend>
                  <div className="set-grid">
                    <IntField
                      label={t('system.security.maxFailures')}
                      value={f.lockout.max_failures}
                      onChange={(v) => set({ lockout: { ...f.lockout, max_failures: v } })}
                      settingKey="security.lockout"
                      field="max_failures"
                      invalid={shown('lockout.max_failures')}
                    />
                    <IntField
                      label={t('system.security.lockMinutes')}
                      value={f.lockout.lock_minutes}
                      onChange={(v) => set({ lockout: { ...f.lockout, lock_minutes: v } })}
                      settingKey="security.lockout"
                      field="lock_minutes"
                      invalid={shown('lockout.lock_minutes')}
                    />
                  </div>
                </fieldset>

                <fieldset className="set-group">
                  <legend>{t('system.security.mfa')}</legend>
                  <div className="set-checks">
                    {MFA_ROLES.map((role) => (
                      <Switch
                        key={role}
                        label={t(`system.roles.${role}`)}
                        checked={new Map(Object.entries(f.mfa)).get(role) === 'required'}
                        onChange={(e) =>
                          set({ mfa: { ...f.mfa, [role]: e.currentTarget.checked ? 'required' : 'optional' } })
                        }
                      />
                    ))}
                  </div>
                  {off.length > 0 ? (
                    <p className="set-danger" role="alert">
                      {t('system.security.mfaOff', { roles: off.map((r) => t(`system.roles.${r}`)).join(', ') })}
                    </p>
                  ) : null}
                </fieldset>

                <fieldset className="set-group">
                  <legend>{t('system.security.networks')}</legend>
                  <Textarea
                    classNames={{ input: 'mono' }}
                    aria-label={t('system.security.networks')}
                    description={t('system.security.networksHint')}
                    autosize
                    minRows={3}
                    value={f.networks}
                    error={shown('networks') ? t('system.security.networksError') : null}
                    onChange={(e) => set({ networks: e.currentTarget.value })}
                  />
                  <TextInput
                    mt="sm"
                    label={t('system.security.alertEmail')}
                    description={t('system.security.alertEmailHint')}
                    value={f.alertEmail}
                    maxLength={254}
                    error={shown('alertEmail') ? t('system.settings.emailError') : null}
                    onChange={(e) => set({ alertEmail: e.currentTarget.value })}
                  />
                </fieldset>
              </div>
            );
          }}
        </SectionForm>
      ) : null}
      {siem.data ? <SiemCard data={siem.data} /> : null}
    </SystemLayout>
  );
}

type SiemForm = {
  enabled: boolean;
  host: string;
  port: number | null;
  ca: string | null;
  client: string | null;
  key: string | null;
  keySet: boolean;
};

function siemForm(values: object): SiemForm {
  const c = valueOf<{
    enabled: boolean;
    host: string | null;
    port: number;
    ca_cert_pem: string | null;
    client_cert_pem: string | null;
  }>(values, 'siem.connection');
  return {
    enabled: c.enabled,
    host: c.host ?? '',
    port: c.port,
    ca: c.ca_cert_pem,
    client: c.client_cert_pem,
    key: null,
    keySet: secretSet(values, 'siem.client_key'),
  };
}

function siemValues(f: SiemForm): Record<string, unknown> {
  return {
    'siem.connection': {
      enabled: f.enabled,
      host: f.host.trim() || null,
      port: f.port,
      ca_cert_pem: f.ca,
      client_cert_pem: f.client,
    },
    ...(f.key !== null ? { 'siem.client_key': f.key } : {}),
  };
}

export function siemErrors(f: SiemForm): string[] {
  const out: string[] = [];
  if (intError(f.port, 'siem.connection', 'port')) out.push('port');
  if (f.enabled && !f.host.trim()) out.push('host');
  if (f.enabled && !f.ca) out.push('ca');
  if (f.key !== null && f.key !== '' && !f.client) out.push('client');
  return out;
}

function SiemCard({ data }: { data: Parameters<typeof SectionForm>[0]['data'] }) {
  const { t } = useTranslation();
  return (
    <SectionForm
      section="siem"
      title={t('system.siem.title')}
      data={data}
      toForm={siemForm}
      toValues={siemValues}
      errors={siemErrors}
      hint={t('system.siem.hint')}
    >
      {(f, set, shown) => (
        <div className="set-groups">
          <Switch
            label={t('system.siem.enabled')}
            checked={f.enabled}
            onChange={(e) => set({ enabled: e.currentTarget.checked })}
          />
          <div className="set-grid">
            <TextInput
              label={t('system.siem.host')}
              value={f.host}
              maxLength={255}
              error={shown('host') ? t('system.siem.hostError') : null}
              onChange={(e) => set({ host: e.currentTarget.value })}
            />
            <IntField
              label={t('system.siem.port')}
              value={f.port}
              onChange={(v) => set({ port: v })}
              settingKey="siem.connection"
              field="port"
              invalid={shown('port')}
            />
          </div>
          <div className="set-checks">
            <PemField label={t('system.siem.ca')} value={f.ca} invalid={shown('ca')} onChange={(v) => set({ ca: v })} />
            <PemField
              label={t('system.siem.client')}
              value={f.client}
              invalid={shown('client')}
              onChange={(v) => set({ client: v })}
            />
          </div>
          {f.key === null && f.keySet ? (
            <div className="auth-secret set-secret">
              <span aria-label={t('system.siem.keySet')}>{t('system.siem.key')}: ••••••</span>
              <button type="button" className="btn-link" onClick={() => set({ key: '' })}>
                {t('system.auth.conn.change')}
              </button>
            </div>
          ) : (
            <PasswordInput
              label={t('system.siem.key')}
              description={t('system.siem.keyHint')}
              value={f.key ?? ''}
              maxLength={65536}
              autoComplete="off"
              onChange={(e) => set({ key: e.currentTarget.value })}
            />
          )}
        </div>
      )}
    </SectionForm>
  );
}

/** Загрузка сертификата PEM (≤ 64 КБ, SEC-WEB-08): «загружен» и «Заменить». */
export function PemField({
  label,
  value,
  invalid,
  onChange,
}: {
  label: string;
  value: string | null;
  invalid: boolean;
  onChange: (v: string | null) => void;
}) {
  const { t } = useTranslation();
  const [problem, setProblem] = useState<'size' | 'format' | null>(null);
  return (
    <div className="auth-row">
      <span className="auth-label">{label}</span>
      {value ? <span className="auth-chip ok">✓ {t('system.auth.conn.caLoaded')}</span> : null}
      <FileButton
        accept=".pem,.crt,.cer"
        onChange={(file) => {
          if (!file) return;
          void file.text().then((text) => {
            const p = certProblem(text, file.size);
            setProblem(p);
            if (!p) onChange(text);
          });
        }}
      >
        {(props) => (
          <Button
            variant="default"
            size="xs"
            aria-label={`${label}: ${value ? t('system.auth.conn.caReplace') : t('system.auth.conn.caUpload')}`}
            {...props}
          >
            {value ? t('system.auth.conn.caReplace') : t('system.auth.conn.caUpload')}
          </Button>
        )}
      </FileButton>
      {value ? (
        <button type="button" className="btn-link" onClick={() => onChange(null)}>
          {t('system.settings.remove')}
        </button>
      ) : null}
      {problem || invalid ? (
        <span className="auth-bad" role="alert">
          {problem ? t(`system.auth.errors.ca_${problem}`) : t('system.settings.required')}
        </span>
      ) : null}
    </div>
  );
}
