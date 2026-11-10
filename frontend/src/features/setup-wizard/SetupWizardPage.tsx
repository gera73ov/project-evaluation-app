/**
 * FE-064 · мастер первичной настройки (SPEC 7.1 шаги 1–5, FR-SA-02): адрес и часовой пояс; почта;
 * способ входа с ветвлением «Приложение» (политика паролей) / AD (параметры, обе проверки);
 * политики безопасности; первый администратор. Индикатор шагов, продолжение с прерванного шага,
 * пройденные шаги можно открыть и поправить. Шаг сохраняется `POST /system/setup/{step}` с
 * `complete: true`; формы — те же, что в разделе «Система».
 */
import { Button, Radio, Select, Stack, TextInput } from '@mantine/core';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { useNavigate } from '../../app/router';
import { api, type components } from '../../shared/api/client';
import { call } from '../../shared/api/problem';
import { ErrorText } from '../../shared/ui/ErrorText';
import { CreateForm, useAdmins } from '../system/admins/AccountsPage';
import { AdForm } from '../system/auth/AuthPage';
import { SmtpFields, smtpErrors, smtpForm, smtpValues } from '../system/settings/MailRetentionPages';
import { SectionForm } from '../system/settings/SectionForm';
import { SecurityFields, securityErrors, securityForm, securityValues } from '../system/settings/SecurityPage';
import { valueOf } from '../system/settings/settings';
import {
  STEPS,
  currentStep,
  isHttpsUrl,
  reachable,
  setupKey,
  timezones,
  useSetup,
  withDefaults,
  type SetupStep,
  type StepName,
} from './setup';

type Mode = 'local' | 'ad';
type Section = components['schemas']['SettingsSection'];

/** Значения шага в форме раздела настроек (те же ключи settings.schema.json). */
const asSection = (section: string, values: Record<string, unknown>) => ({ section, values }) as Section;

export function SetupWizardPage() {
  const { t } = useTranslation();
  const setup = useSetup();
  const steps = setup.data ?? [];
  const current = setup.data ? currentStep(steps) : null;
  const [open, setOpen] = useState<StepName | null>(null);
  const shown = open ?? current;
  const step = steps.find((s) => s.step === shown);

  return (
    <main className="setup">
      <header className="setup-head">
        <h1>{t('setupWizard.title')}</h1>
        <p className="sub">{t('setupWizard.subtitle')}</p>
      </header>
      <ErrorText error={setup.error} />
      {setup.data ? (
        <div className="setup-body">
          <ol className="setup-steps" aria-label={t('setupWizard.stepsLabel')}>
            {STEPS.map((name, i) => {
              const done = steps.find((s) => s.step === name)?.done ?? false;
              const on = name === shown;
              return (
                <li key={name} className={`${done ? 'done' : ''} ${on ? 'on' : ''}`}>
                  <button
                    type="button"
                    disabled={!reachable(name, steps)}
                    aria-current={on ? 'step' : undefined}
                    onClick={() => setOpen(name)}
                  >
                    <span className="setup-n">{done ? '✓' : i + 1}</span>
                    <span>{t(`setupWizard.step.${name}`)}</span>
                  </button>
                </li>
              );
            })}
          </ol>
          <div className="setup-card">
            {step ? <StepView key={step.step} step={step} steps={steps} onNext={() => setOpen(null)} /> : <Finished />}
          </div>
        </div>
      ) : null}
    </main>
  );
}

function Finished() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  return (
    <Stack gap="sm" className="sec setup-done">
      <h2>{t('setupWizard.done.title')}</h2>
      <p>{t('setupWizard.done.text')}</p>
      <div>
        <Button onClick={() => navigate('/system')}>{t('setupWizard.done.toSystem')}</Button>
      </div>
    </Stack>
  );
}

/** Сохранить шаг и перейти к следующему: кэш мастера перечитывается. */
function usePersist(step: StepName, onNext: () => void) {
  const qc = useQueryClient();
  return async (values: Record<string, unknown>) => {
    const res = await call(() =>
      api.POST('/system/setup/{step}', {
        params: { path: { step } },
        body: { values: values as never, complete: true },
      }),
    );
    await qc.invalidateQueries({ queryKey: setupKey });
    onNext();
    // формы шагов 3 и 4 строятся из всех ключей «Безопасности»: недостающие — по умолчанию
    return asSection(step, {
      ...withDefaults('auth', {}),
      ...withDefaults('security', {}),
      ...withDefaults(step, res.values),
    });
  };
}

function StepView({ step, steps, onNext }: { step: SetupStep; steps: readonly SetupStep[]; onNext: () => void }) {
  const { t } = useTranslation();
  const persist = usePersist(step.step, onNext);
  const values = withDefaults(step.step, step.values);
  const data = asSection(step.step, values);
  const next = t(step.done ? 'setupWizard.saveAgain' : 'setupWizard.next');
  const authValues = withDefaults('auth', steps.find((s) => s.step === 'auth')?.values);

  if (step.step === 'app')
    return (
      <SectionForm
        section="app"
        title={t('setupWizard.step.app')}
        data={data}
        toForm={(v) => ({
          url: valueOf<string | null>(v, 'app.base_url') ?? '',
          tz: valueOf<string>(v, 'app.timezone'),
        })}
        toValues={(f) => ({ 'app.base_url': f.url.trim(), 'app.timezone': f.tz })}
        errors={(f) => [...(isHttpsUrl(f.url.trim()) ? [] : ['url']), ...(f.tz ? [] : ['tz'])]}
        hint={t('setupWizard.app.hint')}
        persist={persist}
        saveLabel={next}
        allowClean
      >
        {(f, set, shown) => (
          <div className="set-grid">
            <TextInput
              label={t('setupWizard.app.url')}
              description={t('setupWizard.app.urlHint')}
              placeholder="https://estimator.corp.local"
              value={f.url}
              maxLength={2048}
              error={shown('url') ? t('setupWizard.app.urlError') : null}
              onChange={(e) => set({ url: e.currentTarget.value })}
            />
            <Select
              label={t('setupWizard.app.tz')}
              searchable
              allowDeselect={false}
              value={f.tz}
              data={timezones()}
              error={shown('tz') ? t('system.settings.required') : null}
              onChange={(v) => set({ tz: v ?? '' })}
            />
          </div>
        )}
      </SectionForm>
    );

  if (step.step === 'smtp')
    return (
      <SectionForm
        section="smtp"
        title={t('setupWizard.step.smtp')}
        data={data}
        toForm={smtpForm}
        toValues={smtpValues}
        errors={smtpErrors}
        hint={t('setupWizard.smtp.hint')}
        persist={persist}
        saveLabel={next}
        allowClean
      >
        {(f, set, shown) => <SmtpFields f={f} initial={smtpForm(data.values)} set={set} shown={shown} />}
      </SectionForm>
    );

  if (step.step === 'auth') return <AuthStep data={values} persist={persist} next={next} />;

  if (step.step === 'security')
    return (
      <SectionForm
        section="security"
        title={t('setupWizard.step.security')}
        data={asSection('security', { ...withDefaults('auth', {}), ...values })}
        toForm={securityForm}
        toValues={(f) => {
          const all = securityValues(f);
          return Object.fromEntries(Object.entries(all).filter(([k]) => k !== 'security.password_policy'));
        }}
        errors={(f) => securityErrors(f).filter((e) => !e.startsWith('password.'))}
        hint={t('setupWizard.security.hint')}
        persist={persist}
        saveLabel={next}
        allowClean
      >
        {(f, set, shown) => <SecurityFields f={f} set={set} shown={shown} parts={['policies']} />}
      </SectionForm>
    );

  return <FirstAdmin mode={valueOf<Mode>(authValues, 'auth.mode')} onNext={onNext} />;
}

/** Шаг 3: выбор режима; «Приложение» — политика паролей, AD — параметры каталога и обе проверки. */
function AuthStep({
  data,
  persist,
  next,
}: {
  data: Record<string, unknown>;
  persist: (values: Record<string, unknown>) => Promise<Section>;
  next: string;
}) {
  const { t } = useTranslation();
  const [mode, setMode] = useState<Mode>(valueOf<Mode>(data, 'auth.mode') === 'ad' ? 'ad' : 'local');
  return (
    <Stack gap="md">
      <section className="sec auth-sec" aria-label={t('setupWizard.auth.modeTitle')}>
        <h2>{t('setupWizard.auth.modeTitle')}</h2>
        <Radio.Group value={mode} onChange={(v) => setMode(v === 'ad' ? 'ad' : 'local')}>
          <Stack gap={8}>
            <Radio value="local" label={t('setupWizard.auth.local')} description={t('setupWizard.auth.localHint')} />
            <Radio value="ad" label={t('setupWizard.auth.ad')} description={t('setupWizard.auth.adHint')} />
          </Stack>
        </Radio.Group>
        <p className="auth-warn">ⓘ {t('system.auth.mode.superadmins')}</p>
      </section>
      {mode === 'local' ? (
        <SectionForm
          section="auth"
          title={t('setupWizard.auth.passwordTitle')}
          data={asSection('auth', { ...withDefaults('security', {}), ...data })}
          toForm={securityForm}
          toValues={(f) => ({
            'auth.mode': 'local',
            'security.password_policy': securityValues(f)['security.password_policy'],
          })}
          errors={(f) => securityErrors(f).filter((e) => e.startsWith('password.'))}
          persist={persist}
          saveLabel={next}
          allowClean
        >
          {(f, set, shown) => <SecurityFields f={f} set={set} shown={shown} parts={['password']} />}
        </SectionForm>
      ) : (
        <AdForm values={data} persist={(v) => persist({ ...v, 'auth.mode': 'ad' })} saveLabel={next} />
      )}
    </Stack>
  );
}

/**
 * Шаг 5: первый администратор. В режиме «Приложение» — создать (ссылка активации письмом),
 * в режиме AD — завести заранее, выбрав учётку поиском по каталогу (FR-SA-02, CR-011). «Завершить
 * настройку» доступна, когда есть хотя бы один администратор.
 */
function FirstAdmin({ mode, onNext }: { mode: Mode; onNext: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const admins = useAdmins();
  const [creating, setCreating] = useState(false);
  const all = admins.data?.items ?? [];
  const existing = all.filter((a) => a.roles.includes('admin') && a.status !== 'blocked');
  // пока администраторов нет, форма открыта сразу и не закрывается сама после создания
  const none = Boolean(admins.data) && existing.length === 0;
  if (none && !creating) setCreating(true);
  const finish = useMutation({
    mutationFn: () =>
      call(() =>
        api.POST('/system/setup/{step}', {
          params: { path: { step: 'first_admin' } },
          body: { values: {} as never, complete: true },
        }),
      ),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: setupKey });
      onNext();
    },
  });
  return (
    <Stack gap="sm" className="sec setup-admin">
      <h2>{t('setupWizard.step.first_admin')}</h2>
      <p className="auth-hint">{t(mode === 'ad' ? 'setupWizard.admin.adHint' : 'setupWizard.admin.localHint')}</p>
      <ErrorText error={admins.error} />
      {existing.length > 0 ? (
        <ul className="setup-admins">
          {existing.map((a) => (
            <li key={a.id}>
              <b>{a.full_name}</b> <span className="sub">{a.login}</span> ·{' '}
              <span className={`pill ${a.status === 'active' ? 'ok' : 'warn'}`}>
                {t(`system.accounts.st.${a.status}`)}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
      {creating ? (
        <CreateForm
          kind="admins"
          all={all}
          adminOnly
          ad={mode === 'ad'}
          doneLabel={t('common.close')}
          onDone={() => setCreating(false)}
        />
      ) : (
        <div>
          <Button variant="default" onClick={() => setCreating(true)}>
            + {t('setupWizard.admin.another')}
          </Button>
        </div>
      )}
      <ErrorText error={finish.error} />
      <div className="auth-foot">
        {existing.length === 0 ? <span className="auth-hint">{t('setupWizard.admin.needOne')}</span> : null}
        <Button disabled={existing.length === 0} loading={finish.isPending} onClick={() => finish.mutate()}>
          {t('setupWizard.finish')}
        </Button>
      </div>
    </Stack>
  );
}
