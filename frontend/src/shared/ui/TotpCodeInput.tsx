/**
 * FE-004, FE-005 · код TOTP в 6 клетках (11.1 №6): только цифры, автопереход, Backspace назад,
 * вставка из буфера целиком; после шестой цифры вызывается `onComplete` (автоотправка).
 */
import { useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';

const LENGTH = 6;

export function TotpCodeInput({
  onComplete,
  onChange,
  disabled,
  autoFocus = true,
}: {
  onComplete: (code: string) => void;
  onChange?: (code: string) => void;
  disabled?: boolean;
  autoFocus?: boolean;
}) {
  const { t } = useTranslation();
  const [digits, setDigits] = useState<string[]>(Array.from({ length: LENGTH }, () => ''));
  const refs = useRef<(HTMLInputElement | null)[]>([]);

  function update(next: string[], focus: number) {
    setDigits(next);
    const code = next.join('');
    onChange?.(code);
    refs.current.at(Math.min(focus, LENGTH - 1))?.focus();
    if (code.length === LENGTH) onComplete(code);
  }

  function fill(from: number, text: string) {
    const clean = text.replace(/\D/g, '').slice(0, LENGTH - from);
    if (!clean) return;
    const next = [...digits];
    next.splice(from, clean.length, ...clean.split(''));
    update(next, from + clean.length);
  }

  return (
    <div className="totp" role="group" aria-label={t('auth.totp.cells')}>
      {digits.map((digit, i) => (
        <input
          key={i}
          ref={(el) => {
            refs.current.splice(i, 1, el);
          }}
          value={digit}
          inputMode="numeric"
          autoComplete={i === 0 ? 'one-time-code' : 'off'}
          maxLength={LENGTH}
          aria-label={t('auth.totp.digit', { n: i + 1 })}
          disabled={disabled}
          autoFocus={autoFocus && i === 0}
          onChange={(e) => {
            const value = e.currentTarget.value;
            if (value === '') {
              const next = [...digits];
              next.splice(i, 1, '');
              setDigits(next);
              onChange?.(next.join(''));
              return;
            }
            fill(i, value.slice(-LENGTH));
          }}
          onKeyDown={(e) => {
            if (e.key === 'Backspace' && digit === '' && i > 0) refs.current.at(i - 1)?.focus();
          }}
          onPaste={(e) => {
            e.preventDefault();
            fill(i, e.clipboardData.getData('text'));
          }}
        />
      ))}
    </div>
  );
}
