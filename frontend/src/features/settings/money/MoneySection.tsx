/**
 * FE-014 · блок «Деньги» настроек проекта (SPEC 11.6 №7–9, №13–14; BR-MONEY-01…05, FR-2FA-05;
 * DESIGN.md 10.5).
 *
 * Только с правом `money.read`: у эксперта блока нет в разметке (рисует его ProjectSettingsPage).
 * Правка — `money.write` (модератор); пресейл и руководитель пресейла смотрят. Без пройденного в
 * сессии TOTP сервер отвечает 403 TOTP_REQUIRED — вместо блока «🔒 Подтвердите вход кодом».
 * Каждое поле сохраняется при уходе фокуса `PUT /projects/{id}/money`; суммы считает сервер (6.4).
 */
import { Select, TextInput } from '@mantine/core';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import Decimal from 'decimal.js';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { useNavigate } from '../../../app/router';
import { useSession } from '../../../app/session';
import { api, type components } from '../../../shared/api/client';
import { asDecimalString } from '../../../shared/api/decimal';
import { call } from '../../../shared/api/problem';
import { formatMoney, formatNumber, formatPercent, formatRate } from '../../../shared/format/number';
import { ErrorText } from '../../../shared/ui/ErrorText';
import { MoneyGuard, isTotpRequired } from '../../../shared/ui/MoneyGuard';
import type { Project } from '../useProject';

type Money = components['schemas']['ProjectMoney'];
type MoneyPut = components['schemas']['ProjectMoneyPut'];
type Figure = components['schemas']['MoneyFigure'];

export const moneyKey = (id: string) => ['money', id] as const;

/** Курс: больше 0, не более 4 знаков после запятой → каноническая строка; иначе null. */
export function parseExchangeRate(input: string): string | null {
  const text = input.replace(/\s/g, '').replace(',', '.');
  const [whole = '', fraction, extra] = text.split('.');
  if (extra !== undefined || !/^\d{1,8}$/.test(whole)) return null;
  if (fraction !== undefined && !/^\d{1,4}$/.test(fraction)) return null;
  const value = new Decimal(text);
  return value.gt(0) ? value.toFixed(4) : null;
}

/** Ставка ₽/ч: целое 0–1 000 000; пусто — «не задана» (null); ошибка — undefined. */
export function parseRub(input: string): string | null | undefined {
  const text = input.replace(/\s/g, '');
  if (text === '') return null;
  if (!/^\d{1,7}$/.test(text)) return undefined;
  const value = Number(text);
  return value <= 1_000_000 ? String(value) : undefined;
}

function figureOf(money: Money, key: 'e' | 'p80' | 'p90'): Figure | undefined {
  return new Map(Object.entries(money.figures)).get(key);
}

type VatRate = { id: string; percent: string | null; is_active: boolean };

/** Активные ставки НДС и текущая ставка проекта, даже если её нет в справочнике или он не загрузился. */
export function vatOptions(items: readonly VatRate[], money: Pick<Money, 'vat_rate_id' | 'vat_percent'>): VatRate[] {
  const list = items.filter((v) => v.is_active || v.id === money.vat_rate_id);
  if (list.some((v) => v.id === money.vat_rate_id)) return list;
  const current = {
    id: money.vat_rate_id,
    percent: money.vat_percent === null ? null : String(money.vat_percent),
    is_active: true,
  };
  return [current, ...list];
}

function RateField({
  label,
  value,
  readOnly,
  onCommit,
}: {
  label: string;
  value: string | null;
  readOnly: boolean;
  onCommit: (value: string | null) => void;
}) {
  const { t } = useTranslation();
  const shown = value === null ? '' : formatNumber(value, 0);
  const [draft, setDraft] = useState(shown);
  const [base, setBase] = useState(shown);
  const [error, setError] = useState<string | null>(null);
  if (shown !== base) {
    setBase(shown);
    setDraft(shown);
  }
  return (
    <div className="money-rate">
      <label className="money-rate-label">
        <span>{label}</span>
        <TextInput
          {...(value === null ? { className: 'rate-missing' } : {})}
          aria-label={label}
          value={draft}
          readOnly={readOnly}
          placeholder={t('settings.money.notSet')}
          inputMode="numeric"
          error={error}
          w={150}
          onChange={(e) => setDraft(e.currentTarget.value)}
          onBlur={() => {
            if (draft === shown) return setError(null);
            const parsed = parseRub(draft);
            if (parsed === undefined) return setError(t('settings.money.errors.rub'));
            setError(null);
            onCommit(parsed);
          }}
        />
      </label>
    </div>
  );
}

export function MoneySection({ project, readOnly }: { project: Project; readOnly: boolean }) {
  const { t } = useTranslation();
  const client = useQueryClient();
  const navigate = useNavigate();
  const { session } = useSession();
  const canWrite = !readOnly && project.my_permissions.includes('money.write');

  const money = useQuery({
    queryKey: moneyKey(project.id),
    queryFn: () =>
      call(() =>
        api.GET('/projects/{id}/money', {
          params: { path: { id: project.id } },
        }),
      ),
    select: (data) => data as Money,
  });
  const currencies = useQuery({
    queryKey: ['dict', 'currencies'],
    queryFn: () => call(() => api.GET('/admin/currencies')),
    staleTime: 10 * 60_000,
    enabled: money.isSuccess,
  });
  const vatRates = useQuery({
    queryKey: ['dict', 'vat-rates'],
    queryFn: () => call(() => api.GET('/admin/vat-rates')),
    staleTime: 10 * 60_000,
    enabled: money.isSuccess,
  });
  const put = useMutation({
    mutationFn: (body: MoneyPut) =>
      call(() =>
        api.PUT('/projects/{id}/money', {
          params: { path: { id: project.id } },
          body,
        }),
      ),
    onSuccess: (data) => client.setQueryData(moneyKey(project.id), data),
  });

  const [rateDraft, setRateDraft] = useState<string | null>(null);
  const [rateError, setRateError] = useState<string | null>(null);

  const totpEnabled = session.state === 'ready' ? session.me.totp_enabled : false;
  const data = money.data;
  const disciplineName = new Map(project.disciplines.map((d) => [d.discipline_id, d.name]));
  const nameOf = (id: string) => (id === 'pm' ? t('settings.money.pm') : (disciplineName.get(id) ?? id));

  function rateOf(disciplineId: string | null): string | null {
    return data?.rates.find((r) => r.discipline_id === disciplineId)?.rate_rub ?? null;
  }
  function commitRate(disciplineId: string | null, value: string | null) {
    if (!data) return;
    const rows = [...project.disciplines.map((d) => d.discipline_id), null].map((id) => ({
      discipline_id: id,
      rate_rub: id === disciplineId ? value : rateOf(id),
    }));
    put.mutate({ rates: rows });
  }

  const quote = data ? figureOf(data, project.quote_figure) : undefined;
  const e = data ? figureOf(data, 'e') : undefined;
  const rub = data?.currency === 'RUB';
  const pair = (inRub: string | null | undefined, inCur: string | null | undefined) =>
    rub || !data
      ? formatMoney(inRub ?? null)
      : `${formatMoney(inRub ?? null)} · ${formatMoney(inCur ?? null, data.currency)}`;
  const missing = data?.rates_missing ?? [];
  const blocked = missing.length > 0 && e?.total_rub === null;

  return (
    <section className="sec set-sec money-sec" aria-labelledby="set-money">
      <div className="sec-head">
        <h3 id="set-money">{t('settings.money.title')}</h3>
        <span className="sp" />
        <span className="lock">
          <span aria-hidden="true">🔒</span> {t('settings.money.who')}
        </span>
      </div>
      <MoneyGuard
        error={money.error}
        totpEnabled={totpEnabled}
        onUnlocked={() => void money.refetch()}
        onEnroll={() => navigate('/profile')}
      >
        {!isTotpRequired(money.error) ? <ErrorText error={money.error ?? put.error} /> : null}
        {data ? (
          <>
            <div className="set-row">
              <label className="set-label" htmlFor="money-currency">
                {t('settings.money.currency')}
              </label>
              <div className="set-inline">
                <Select
                  id="money-currency"
                  w={120}
                  value={data.currency}
                  readOnly={!canWrite}
                  allowDeselect={false}
                  data={(currencies.data?.items ?? [{ code: data.currency, symbol: '', is_active: true }])
                    .filter((c) => c.is_active || c.code === data.currency)
                    .map((c) => c.code)}
                  onChange={(code) => code && code !== data.currency && put.mutate({ currency: code })}
                />
                {!rub ? (
                  <>
                    <span className="set-unit">{t('settings.money.rate')}</span>
                    <TextInput
                      aria-label={t('settings.money.rate')}
                      w={130}
                      className="num"
                      value={rateDraft ?? formatRate(String(data.exchange_rate))}
                      readOnly={!canWrite}
                      error={rateError}
                      onChange={(ev) => setRateDraft(ev.currentTarget.value)}
                      onBlur={() => {
                        if (rateDraft === null) return;
                        const parsed = parseExchangeRate(rateDraft);
                        if (!parsed) return setRateError(t('settings.money.errors.rate'));
                        setRateError(null);
                        setRateDraft(null);
                        if (parsed !== new Decimal(String(data.exchange_rate)).toFixed(4)) {
                          put.mutate({
                            exchange_rate: asDecimalString(parsed),
                          });
                        }
                      }}
                    />
                    <span className="set-unit">{t('settings.money.perUnit', { currency: data.currency })}</span>
                  </>
                ) : null}
              </div>
            </div>
            {!rub ? <p className="set-hint money-note">{t('settings.money.rateNote')}</p> : null}

            <div className="set-row">
              <label className="set-label" htmlFor="money-vat">
                {t('settings.money.vat')}
              </label>
              <div className="set-inline">
                <Select
                  id="money-vat"
                  w={150}
                  value={data.vat_rate_id}
                  readOnly={!canWrite}
                  allowDeselect={false}
                  data={vatOptions(
                    (vatRates.data?.items ?? []).map((v) => ({
                      id: v.id,
                      percent: v.percent === null ? null : String(v.percent),
                      is_active: v.is_active,
                    })),
                    data,
                  ).map((v) => ({
                    value: v.id,
                    label: v.percent === null ? t('settings.money.vatNone') : formatPercent(String(v.percent)),
                  }))}
                  onChange={(id) => id && id !== data.vat_rate_id && put.mutate({ vat_rate_id: id })}
                />
                <span className="set-hint">{t('settings.money.vatNote')}</span>
              </div>
            </div>

            <div className="lbl money-rates-title">{t('settings.money.rates')}</div>
            {project.disciplines.map((d) => (
              <RateField
                key={d.discipline_id}
                label={d.name}
                value={rateOf(d.discipline_id)}
                readOnly={!canWrite}
                onCommit={(value) => commitRate(d.discipline_id, value)}
              />
            ))}
            <RateField
              label={t('settings.money.pm')}
              value={rateOf(null)}
              readOnly={!canWrite}
              onCommit={(value) => commitRate(null, value)}
            />

            <dl className="money-totals">
              <dt>{t('settings.money.totalNoVat')}</dt>
              <dd className="strong">{pair(e?.total_rub, e?.total_cur)}</dd>
              {data.vat_percent !== null ? (
                <>
                  <dt>
                    {t('settings.money.vatLine', {
                      percent: formatPercent(String(data.vat_percent)),
                    })}
                  </dt>
                  <dd>{formatMoney(e?.vat_rub ?? null)}</dd>
                  <dt>{t('settings.money.totalVat')}</dt>
                  <dd className="strong">{pair(e?.total_with_vat_rub, e?.total_with_vat_cur)}</dd>
                </>
              ) : null}
              <dt>
                {t('settings.money.quote', {
                  figure: t(`home.figure.${project.quote_figure}`),
                })}
              </dt>
              <dd className="strong">
                {rub
                  ? `${formatMoney(quote?.total_rub ?? null)} / ${formatMoney(quote?.total_with_vat_rub ?? null)}`
                  : `${formatMoney(quote?.total_cur ?? null, data.currency)} / ${formatMoney(
                      quote?.total_with_vat_cur ?? null,
                      data.currency,
                    )}`}
              </dd>
            </dl>

            {missing.length > 0 ? (
              <div className="warnbox" role="status">
                {blocked
                  ? t('settings.money.missingBlocked', {
                      names: missing.map(nameOf).join(', '),
                    })
                  : t('settings.money.missingCounted', {
                      names: missing.map(nameOf).join(', '),
                    })}
              </div>
            ) : null}
            <p className="set-hint">{t('settings.money.footer')}</p>
          </>
        ) : null}
      </MoneyGuard>
    </section>
  );
}
