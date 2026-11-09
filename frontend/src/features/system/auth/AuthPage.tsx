/**
 * FE-061 · «Аутентификация» (SPEC 11.2 №2–6, макет `sa-auth.png`, FR-AUTH-AD-01…07, FR-SA-03):
 * 2 — текущий способ входа; в режиме «Приложение» — «Перейти на Active Directory…», в режиме AD —
 *     итог перехода; обратного переключателя нет; подсказка «суперадминистраторы входят локально».
 * 3 — подключение: контроллеры, LDAPS / StartTLS (без нешифрованного), сертификат УЦ, Base DN,
 *     фильтр, сервисная учётка (пароль — только «изменить»), «Проверить подключение» со временем.
 * 4 — группа доступа и роли по группам (только «Модератор» и «Пресейл»); включение сопоставления
 *     сначала подтверждается.
 * 5 — тестовый вход: ФИО, email, состояние учётки, группы и итоговая роль; пароль не сохраняется.
 * 6 — «Сохранить…» неактивна, пока после последнего изменения не прошли обе проверки; step-up.
 */
import { Button, Checkbox, FileButton, NumberInput, PasswordInput, Radio, Select, TextInput } from '@mantine/core';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

import type { Me } from '../../../app/session';
import { api, type components } from '../../../shared/api/client';
import { call } from '../../../shared/api/problem';
import { formatDateTime } from '../../../shared/format/date';
import { ConfirmDialog } from '../../../shared/ui/ConfirmDialog';
import { ErrorText } from '../../../shared/ui/ErrorText';
import { SystemLayout, settingsKey } from '../layout/SystemLayout';
import { StepUpCancelled, useStepUp } from '../layout/useStepUp';
import {
  MAX_CONTROLLERS,
  MAX_GROUPS,
  authMode,
  certProblem,
  formOf,
  groupName,
  seconds,
  signature,
  validate,
  valuesOf,
  type AuthForm,
  type FieldError,
} from './auth';
import { SwitchReportModal, SwitchWizard, ReportCounts, type SwitchResult } from './SwitchWizard';

type AdTestResult = components['schemas']['AdTestResult'];

/** Итог перехода живёт в кэше сессии: в контракте его нет (см. описание PR). */
const switchKey = ['system', 'auth', 'switch-result'] as const;

export function AuthPage({ me }: { me: Me }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const settings = useQuery({
    queryKey: settingsKey('auth'),
    queryFn: () => call(() => api.GET('/system/settings/{section}', { params: { path: { section: 'auth' } } })),
  });
  const switched = useQuery<SwitchResult | null>({
    queryKey: switchKey,
    queryFn: () => null,
    staleTime: Infinity,
    gcTime: Infinity,
  });
  const [wizard, setWizard] = useState(false);
  const [reportOpen, setReportOpen] = useState(false);
  const mode = settings.data ? authMode(settings.data.values) : null;

  return (
    <SystemLayout active="auth" title={t('system.menu.auth')} subtitle={t('system.auth.subtitle')}>
      <ErrorText error={settings.error} />
      {settings.data && mode ? (
        <>
          <section className="sec auth-sec" aria-labelledby="auth-mode">
            <h2 id="auth-mode">{t('system.auth.mode.title')}</h2>
            <div className="auth-mode">
              <span className="auth-dot" aria-hidden="true" />
              <div>
                <b>{t(`system.auth.mode.${mode}`)}</b>
                <p>{t(`system.auth.mode.${mode}Hint`)}</p>
              </div>
              <div className="auth-mode-side">
                {mode === 'local' ? (
                  <Button variant="default" onClick={() => setWizard(true)}>
                    {t('system.auth.mode.toAd')}
                  </Button>
                ) : switched.data ? (
                  <>
                    <div>
                      {t('system.auth.mode.switchedAt', {
                        at: formatDateTime(switched.data.at, me.timezone ?? undefined),
                      })}
                    </div>
                    <div>
                      <ReportCounts report={switched.data.report} resolved={switched.data.resolved} />{' '}
                      <button type="button" className="btn-link" onClick={() => setReportOpen(true)}>
                        {t('system.auth.mode.report')}
                      </button>
                    </div>
                  </>
                ) : null}
              </div>
            </div>
            <p className="auth-warn">
              ⓘ {mode === 'ad' ? `${t('system.auth.mode.noBack')} ` : ''}
              {t('system.auth.mode.superadmins')}
            </p>
          </section>
          <AdForm key={JSON.stringify(settings.data.values)} values={settings.data.values} />
          <SwitchWizard
            opened={wizard}
            onClose={() => setWizard(false)}
            onDone={(result) => {
              qc.setQueryData(switchKey, result);
              void qc.invalidateQueries({ queryKey: settingsKey('auth') });
            }}
          />
          <SwitchReportModal
            result={reportOpen ? (switched.data ?? null) : null}
            onClose={() => setReportOpen(false)}
          />
        </>
      ) : null}
    </SystemLayout>
  );
}

function AdForm({ values }: { values: object }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { run, modal } = useStepUp();
  const initial = formOf(values);
  const [form, setForm] = useState<AuthForm>(initial);
  const [showErrors, setShowErrors] = useState(false);
  const [connResult, setConnResult] = useState<{ sig: string; result: AdTestResult } | null>(null);
  const [loginResult, setLoginResult] = useState<{ sig: string; result: AdTestResult } | null>(null);
  const [testLogin, setTestLogin] = useState('');
  const [testPassword, setTestPassword] = useState('');
  const [confirmMapping, setConfirmMapping] = useState(false);
  const [certError, setCertError] = useState<'size' | 'format' | null>(null);
  const [saved, setSaved] = useState(false);

  const sig = signature(form);
  const dirty = sig !== signature(initial);
  const errors = validate(form);
  const err = (f: FieldError) => (showErrors && errors.includes(f) ? t(`system.auth.errors.${f}`) : null);
  const connOk = connResult?.sig === sig && connResult.result.ok;
  const loginOk = loginResult?.sig === sig && loginResult.result.ok;

  const set = <K extends keyof AuthForm>(key: K, value: AuthForm[K]) => {
    setSaved(false);
    setForm((f) => ({ ...f, [key]: value }));
  };
  const setAt = (key: 'controllers' | 'accessGroups', i: number, value: string) =>
    set(
      key,
      (key === 'controllers' ? form.controllers : form.accessGroups).map((v, j) => (j === i ? value : v)),
    );

  const testConn = useMutation({
    mutationFn: () =>
      call(() => api.POST('/system/auth/ad/test-connection', { body: { values: valuesOf(form) as never } })),
    onSuccess: (result) => setConnResult({ sig, result }),
  });
  const testLoginM = useMutation({
    mutationFn: () =>
      call(() => api.POST('/system/auth/ad/test-login', { body: { login: testLogin.trim(), password: testPassword } })),
    onSuccess: (result) => {
      setLoginResult({ sig, result });
      setTestPassword('');
    },
  });
  const save = useMutation({
    mutationFn: () =>
      run(() =>
        call(() =>
          api.PUT('/system/settings/{section}', {
            params: { path: { section: 'auth' } },
            body: { values: valuesOf(form) as never },
          }),
        ),
      ),
    onSuccess: (data) => {
      qc.setQueryData(settingsKey('auth'), data);
      setSaved(true);
    },
  });
  useEffect(() => {
    if (!saved) return;
    const id = setTimeout(() => setSaved(false), 4000);
    return () => clearTimeout(id);
  }, [saved]);

  function check(action: () => void) {
    setShowErrors(true);
    if (errors.length === 0) action();
  }

  const saveError = save.error instanceof StepUpCancelled ? null : save.error;
  const canSave = dirty && errors.length === 0 && connOk && loginOk;

  return (
    <>
      <section className="sec auth-sec" aria-labelledby="auth-conn">
        <h2 id="auth-conn">{t('system.auth.conn.title')}</h2>
        <div className="auth-grid">
          <span className="auth-label">{t('system.auth.conn.controllers')}</span>
          <div className="auth-row">
            {form.controllers.map((c, i) => (
              <TextInput
                key={i}
                className="auth-ctrl"
                aria-label={t('system.auth.conn.controllerN', { n: i + 1 })}
                placeholder="dc1.corp.local:636"
                value={c}
                error={i === 0 ? (err('controllers') ?? err('controller')) : undefined}
                onChange={(e) => setAt('controllers', i, e.currentTarget.value)}
                rightSection={
                  form.controllers.length > 1 ? (
                    <button
                      type="button"
                      className="icon-btn"
                      aria-label={t('system.auth.conn.removeController', { n: i + 1 })}
                      onClick={() =>
                        set(
                          'controllers',
                          form.controllers.filter((_, j) => j !== i),
                        )
                      }
                    >
                      ×
                    </button>
                  ) : null
                }
              />
            ))}
            {form.controllers.length < MAX_CONTROLLERS ? (
              <Button variant="default" size="xs" onClick={() => set('controllers', [...form.controllers, ''])}>
                + {t('system.auth.conn.add')}
              </Button>
            ) : null}
          </div>

          <span className="auth-label" id="auth-proto">
            {t('system.auth.conn.protocol')}
          </span>
          <div className="auth-row">
            <Radio.Group
              aria-labelledby="auth-proto"
              value={form.protocol}
              onChange={(v) => set('protocol', v === 'starttls' ? 'starttls' : 'ldaps')}
            >
              <div className="auth-row">
                <Radio value="ldaps" label="LDAPS" />
                <Radio value="starttls" label="StartTLS" />
              </div>
            </Radio.Group>
            <span className="auth-muted">{t('system.auth.conn.noPlain')}</span>
            <span className="auth-label">{t('system.auth.conn.ca')}</span>
            {form.caCert ? <span className="auth-chip ok">✓ {t('system.auth.conn.caLoaded')}</span> : null}
            <FileButton
              accept=".pem,.crt,.cer"
              onChange={(file) => {
                if (!file) return;
                void file.text().then((text) => {
                  const problem = certProblem(text, file.size);
                  setCertError(problem);
                  if (!problem) set('caCert', text);
                });
              }}
            >
              {(props) => (
                <Button variant="default" size="xs" {...props}>
                  {form.caCert ? t('system.auth.conn.caReplace') : t('system.auth.conn.caUpload')}
                </Button>
              )}
            </FileButton>
            {certError ? (
              <span className="auth-bad" role="alert">
                {t(`system.auth.errors.ca_${certError}`)}
              </span>
            ) : null}
          </div>

          <label className="auth-label" htmlFor="auth-base">
            Base DN
          </label>
          <TextInput
            id="auth-base"
            className="mono"
            value={form.baseDn}
            error={err('baseDn')}
            onChange={(e) => set('baseDn', e.currentTarget.value)}
          />

          <label className="auth-label" htmlFor="auth-filter">
            {t('system.auth.conn.filter')}
          </label>
          <TextInput
            id="auth-filter"
            className="mono"
            value={form.userFilter}
            error={err('userFilter')}
            onChange={(e) => set('userFilter', e.currentTarget.value)}
          />

          <label className="auth-label" htmlFor="auth-bind">
            {t('system.auth.conn.bind')}
          </label>
          <div className="auth-bind">
            <TextInput
              id="auth-bind"
              className="mono"
              value={form.bindDn}
              error={err('bindDn')}
              onChange={(e) => set('bindDn', e.currentTarget.value)}
            />
            {form.bindPassword === null && form.passwordSet ? (
              <div className="auth-secret">
                <span aria-label={t('system.auth.conn.passwordSet')}>••••••</span>
                <button type="button" className="btn-link" onClick={() => set('bindPassword', '')}>
                  {t('system.auth.conn.change')}
                </button>
              </div>
            ) : (
              <PasswordInput
                aria-label={t('system.auth.conn.password')}
                placeholder={t('system.auth.conn.password')}
                value={form.bindPassword ?? ''}
                error={err('bindPassword')}
                maxLength={512}
                autoComplete="new-password"
                onChange={(e) => set('bindPassword', e.currentTarget.value)}
              />
            )}
          </div>
        </div>

        <details className="auth-details">
          <summary>{t('system.auth.conn.more')}</summary>
          <div className="auth-grid">
            <span className="auth-label">{t('system.auth.conn.loginAttr')}</span>
            <Select
              aria-label={t('system.auth.conn.loginAttr')}
              data={['sAMAccountName', 'userPrincipalName']}
              value={form.loginAttribute}
              allowDeselect={false}
              onChange={(v) =>
                set('loginAttribute', v === 'userPrincipalName' ? 'userPrincipalName' : 'sAMAccountName')
              }
            />
            <label className="auth-label" htmlFor="auth-attr-name">
              {t('system.auth.conn.attrName')}
            </label>
            <TextInput
              id="auth-attr-name"
              value={form.attrFullName}
              maxLength={64}
              onChange={(e) => set('attrFullName', e.currentTarget.value)}
            />
            <label className="auth-label" htmlFor="auth-attr-email">
              {t('system.auth.conn.attrEmail')}
            </label>
            <TextInput
              id="auth-attr-email"
              value={form.attrEmail}
              maxLength={64}
              onChange={(e) => set('attrEmail', e.currentTarget.value)}
            />
            <label className="auth-label" htmlFor="auth-attr-dep">
              {t('system.auth.conn.attrDepartment')}
            </label>
            <TextInput
              id="auth-attr-dep"
              value={form.attrDepartment}
              maxLength={64}
              onChange={(e) => set('attrDepartment', e.currentTarget.value)}
            />
            <label className="auth-label" htmlFor="auth-timeout">
              {t('system.auth.conn.timeout')}
            </label>
            <NumberInput
              id="auth-timeout"
              min={1}
              max={60}
              allowDecimal={false}
              value={form.timeout}
              error={err('timeout')}
              onChange={(v) => set('timeout', typeof v === 'number' ? v : Number(v))}
            />
          </div>
        </details>

        <div className="auth-check">
          <Button variant="default" loading={testConn.isPending} onClick={() => check(() => testConn.mutate())}>
            {t('system.auth.conn.test')}
          </Button>
          <TestOutcome
            result={connResult?.sig === sig ? connResult.result : null}
            okText={(r) => t('system.auth.conn.ok', { detail: r.detail ?? '', s: seconds(r.elapsed_ms) })}
          />
          <ErrorText error={testConn.error} />
        </div>
      </section>

      <div className="auth-pair">
        <section className="sec auth-sec" aria-labelledby="auth-roles">
          <h2 id="auth-roles">{t('system.auth.roles.title')}</h2>
          <div className="auth-grid narrow">
            {form.accessGroups.map((g, i) => (
              <GroupRow
                key={i}
                label={i === 0 ? t('system.auth.roles.access') : ''}
                aria={t('system.auth.roles.accessN', { n: i + 1 })}
                value={g}
                error={i === 0 ? err('accessGroups') : null}
                onChange={(v) => setAt('accessGroups', i, v)}
                onRemove={
                  form.accessGroups.length > 1
                    ? () =>
                        set(
                          'accessGroups',
                          form.accessGroups.filter((_, j) => j !== i),
                        )
                    : null
                }
              />
            ))}
            <span />
            <div>
              {form.accessGroups.length < MAX_GROUPS ? (
                <Button variant="default" size="xs" onClick={() => set('accessGroups', [...form.accessGroups, ''])}>
                  + {t('system.auth.roles.addGroup')}
                </Button>
              ) : null}
            </div>
          </div>
          <Checkbox
            my="sm"
            label={t('system.auth.roles.mapping')}
            checked={form.mappingEnabled}
            onChange={(e) => {
              if (e.currentTarget.checked) setConfirmMapping(true);
              else set('mappingEnabled', false);
            }}
          />
          {form.mappingEnabled ? (
            <div className="auth-grid narrow">
              <GroupRow
                label={t('system.roles.moderator')}
                aria={t('system.auth.roles.groupFor', { role: t('system.roles.moderator') })}
                value={form.moderatorGroup}
                error={err('mapping')}
                onChange={(v) => set('moderatorGroup', v)}
                onRemove={null}
              />
              <GroupRow
                label={t('system.roles.presale')}
                aria={t('system.auth.roles.groupFor', { role: t('system.roles.presale') })}
                value={form.presaleGroup}
                error={null}
                onChange={(v) => set('presaleGroup', v)}
                onRemove={null}
              />
            </div>
          ) : null}
          <p className="auth-hint">{t('system.auth.roles.hint')}</p>
        </section>

        <section className="sec auth-sec" aria-labelledby="auth-test">
          <h2 id="auth-test">{t('system.auth.test.title')}</h2>
          <div className="auth-login">
            <TextInput
              aria-label={t('system.auth.test.login')}
              placeholder={t('system.auth.test.login')}
              value={testLogin}
              maxLength={254}
              autoComplete="off"
              onChange={(e) => setTestLogin(e.currentTarget.value)}
            />
            <PasswordInput
              aria-label={t('system.auth.test.password')}
              placeholder={t('system.auth.test.password')}
              value={testPassword}
              maxLength={128}
              autoComplete="off"
              onChange={(e) => setTestPassword(e.currentTarget.value)}
            />
            <Button
              variant="default"
              disabled={!testLogin.trim() || !testPassword}
              loading={testLoginM.isPending}
              onClick={() => check(() => testLoginM.mutate())}
            >
              {t('system.auth.test.run')}
            </Button>
          </div>
          {loginResult?.sig === sig ? <LoginOutcome result={loginResult.result} /> : null}
          <ErrorText error={testLoginM.error} />
          <p className="auth-hint">{t('system.auth.test.hint')}</p>
        </section>
      </div>

      <div className="auth-foot">
        <span className="auth-hint">
          {dirty && !(connOk && loginOk) ? t('system.auth.save.needChecks') : t('system.auth.save.hint')}
        </span>
        <ErrorText error={saveError} />
        {saved ? (
          <span className="auth-ok" role="status">
            ✓ {t('system.auth.save.done')}
          </span>
        ) : null}
        <Button
          variant="default"
          disabled={!dirty}
          onClick={() => {
            setForm(initial);
            setShowErrors(false);
            setCertError(null);
            save.reset();
          }}
        >
          {t('common.cancel')}
        </Button>
        <Button disabled={!canSave} loading={save.isPending} onClick={() => save.mutate()}>
          {t('system.auth.save.button')}
        </Button>
      </div>

      <ConfirmDialog
        opened={confirmMapping}
        title={t('system.auth.roles.confirmTitle')}
        message={t('system.auth.roles.confirmText')}
        confirmLabel={t('system.auth.roles.confirmButton')}
        onCancel={() => setConfirmMapping(false)}
        onConfirm={() => {
          setConfirmMapping(false);
          set('mappingEnabled', true);
        }}
      />
      {modal}
    </>
  );
}

function GroupRow({
  label,
  aria,
  value,
  error,
  onChange,
  onRemove,
}: {
  label: string;
  aria: string;
  value: string;
  error: string | null;
  onChange: (v: string) => void;
  onRemove: (() => void) | null;
}) {
  const { t } = useTranslation();
  return (
    <>
      <span className="auth-label">{label}</span>
      <TextInput
        className="mono"
        aria-label={aria}
        placeholder="CN=APP-Estimator-Users,OU=Groups,…"
        value={value}
        error={error}
        maxLength={1024}
        onChange={(e) => onChange(e.currentTarget.value)}
        rightSection={
          onRemove ? (
            <button
              type="button"
              className="icon-btn"
              aria-label={t('system.auth.roles.remove', { name: aria })}
              onClick={onRemove}
            >
              ×
            </button>
          ) : null
        }
      />
    </>
  );
}

function TestOutcome({ result, okText }: { result: AdTestResult | null; okText: (r: AdTestResult) => string }) {
  const { t } = useTranslation();
  if (!result) return null;
  return result.ok ? (
    <span className="auth-ok" role="status">
      ✓ {okText(result)}
    </span>
  ) : (
    <span className="auth-bad" role="alert">
      ✕ {result.detail ?? t('system.auth.test.failed')}
    </span>
  );
}

function LoginOutcome({ result }: { result: AdTestResult }) {
  const { t } = useTranslation();
  const u = result.user;
  if (!u)
    return (
      <div className="auth-result bad" role="alert">
        ✕ {result.detail ?? t('system.auth.test.failed')}
      </div>
    );
  const roles = u.roles.length
    ? u.roles.map((r) => `«${t(`system.roles.${r}`)}»`).join(', ')
    : `«${t('system.roles.user')}»`;
  return (
    <div className={result.ok ? 'auth-result' : 'auth-result bad'} role="status">
      <div>
        <b>✓ {t('system.auth.test.found')}</b> {u.full_name}
        {u.email ? `, ${u.email}` : ''}
      </div>
      <div>
        {u.disabled ? (
          <b className="bad-ink">✕ {t('system.auth.test.disabled')}</b>
        ) : (
          <b>✓ {t('system.auth.test.active')}</b>
        )}
      </div>
      <div>
        {u.in_access_group ? (
          <>
            <b>✓ {t('system.auth.test.groups')}</b> {u.groups.map(groupName).join(', ')} →{' '}
            {t('system.auth.test.role', { roles })}
          </>
        ) : (
          <b className="bad-ink">✕ {t('system.auth.test.noAccess')}</b>
        )}
      </div>
    </div>
  );
}
