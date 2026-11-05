/** FE-004 · UI-компоненты: автоссылки, статусы, часы, код TOTP, step-up, заглушка денег, QR. */
import { fireEvent, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { ApiError } from '../api/problem';
import { server } from '../../test/setup';
import { HttpResponse, api, http, problem, renderUi } from '../../test/render';
import { AutoLinkText, safeHref, splitLinks } from './AutoLinkText';
import { ConfirmDialog } from './ConfirmDialog';
import { EmptyState } from './EmptyState';
import { HoursInput } from './HoursInput';
import { MoneyGuard, isTotpRequired } from './MoneyGuard';
import { QrCode, qrPath } from './QrCode';
import { StatusBadge } from './StatusBadge';
import { StepUpModal } from './StepUpModal';
import { TotpCodeInput } from './TotpCodeInput';

const totpRequired = new ApiError(403, {
  type: 'about:blank',
  title: 'TOTP_REQUIRED',
  status: 403,
  code: 'TOTP_REQUIRED',
  error_id: 'e',
});

describe('AutoLinkText (FR-DISC-02, SEC-WEB-02)', () => {
  it('ссылками становятся только http и https; хвостовая пунктуация не входит в адрес', () => {
    expect(splitLinks('См. https://wiki.local/a?b=1, и http://x.ru.')).toEqual([
      { text: 'См. ', href: null },
      { text: 'https://wiki.local/a?b=1', href: 'https://wiki.local/a?b=1' },
      { text: ', и ', href: null },
      { text: 'http://x.ru', href: 'http://x.ru/' },
      { text: '.', href: null },
    ]);
    expect(safeHref('javascript:alert(1)')).toBeNull();
    expect(safeHref('data:text/html,x')).toBeNull();
    expect(safeHref('not a url')).toBeNull();
  });

  it('javascript: и разметка остаются текстом, ссылки открываются в новой вкладке', () => {
    const { container } = renderUi(<AutoLinkText text={'javascript:alert(1) <b>жирный</b> https://ok.example/путь'} />);
    const links = container.querySelectorAll('a');
    expect(links).toHaveLength(1);
    expect(links[0]?.getAttribute('href')).toBe('https://ok.example/%D0%BF%D1%83%D1%82%D1%8C');
    expect(links[0]?.getAttribute('rel')).toBe('noopener noreferrer nofollow');
    expect(links[0]?.getAttribute('target')).toBe('_blank');
    expect(container.querySelector('b')).toBeNull();
    expect(container.textContent).toContain('<b>жирный</b>');
  });
});

describe('StatusBadge (DESIGN.md 7.1, 7.2)', () => {
  it('статус ветки несёт символ и текст, не только цвет', () => {
    const { container } = renderUi(
      <>
        <StatusBadge kind="branch" status="draft" />
        <StatusBadge kind="branch" status="done" />
        <StatusBadge kind="project" status="consolidation" />
        <StatusBadge kind="project" status="unknown" />
      </>,
    );
    const pills = [...container.querySelectorAll('.pill')];
    expect(pills.map((p) => p.textContent)).toEqual(['✎черновик', '✓готово', 'Сведение', 'unknown']);
    expect(pills.map((p) => p.className)).toEqual(['pill warn', 'pill ok', 'pill warn', 'pill gray']);
  });
});

describe('HoursInput (FR-TREE-21, BR-CALC-03)', () => {
  function setup(value: string | null = null) {
    const onCommit = vi.fn();
    renderUi(<HoursInput label="R" value={value} onCommit={onCommit} />);
    const input = screen.getByLabelText('R') as HTMLInputElement;
    const type = (text: string) => {
      fireEvent.change(input, { target: { value: text } });
      fireEvent.blur(input);
    };
    return { input, onCommit, type };
  }

  it('запятая, округление до 0,5 с подсказкой, каноническое значение для API', () => {
    const { input, onCommit, type } = setup('8');
    expect(input.value).toBe('8');
    type('12,3');
    expect(onCommit).toHaveBeenLastCalledWith('12.5');
    expect(input.value).toBe('12,5');
    expect(screen.getByRole('status').textContent).toBe('округлено до 12,5');
    type('4.5');
    expect(onCommit).toHaveBeenLastCalledWith('4.5');
    expect(screen.queryByRole('status')).toBeNull();
  });

  it('пусто — null; вне диапазона и не число — ошибка без отправки', () => {
    const { onCommit, type } = setup();
    type('');
    expect(onCommit).toHaveBeenLastCalledWith(null);
    onCommit.mockClear();
    type('100000');
    expect(screen.getByText('От 0 до 99 999,5')).toBeTruthy();
    type('абв');
    expect(screen.getByText('Введите число, например 12,5')).toBeTruthy();
    expect(onCommit).not.toHaveBeenCalled();
  });
});

describe('TotpCodeInput (11.1 №6)', () => {
  it('цифра за цифрой с автопереходом; на шестой — onComplete', () => {
    const onComplete = vi.fn();
    renderUi(<TotpCodeInput onComplete={onComplete} />);
    const cells = screen.getAllByRole('textbox') as HTMLInputElement[];
    expect(cells).toHaveLength(6);
    expect(cells[0]?.getAttribute('autocomplete')).toBe('one-time-code');
    const typeInFocused = (value: string) => {
      const focused = document.activeElement;
      if (!(focused instanceof HTMLInputElement)) throw new Error('нет фокуса');
      fireEvent.change(focused, { target: { value } });
    };
    for (const digit of ['1', '2', 'x', '3', '4', '5']) typeInFocused(digit);
    expect(onComplete).not.toHaveBeenCalled();
    typeInFocused('6');
    expect(cells.map((c) => c.value).join('')).toBe('123456');
    expect(onComplete).toHaveBeenCalledWith('123456');
  });

  it('Backspace в пустой клетке возвращает фокус назад', () => {
    renderUi(<TotpCodeInput onComplete={() => {}} />);
    const cells = screen.getAllByRole('textbox');
    const [first, second] = cells;
    if (!first || !second) throw new Error('нет клеток');
    fireEvent.change(first, { target: { value: '7' } });
    expect(document.activeElement).toBe(second);
    fireEvent.keyDown(second, { key: 'Backspace' });
    expect(document.activeElement).toBe(first);
  });
});

describe('StepUpModal (SEC-AUTH-05)', () => {
  it('пароль и код; неверно — текст STEP_UP_FAILED и новые клетки; верно — onSuccess', async () => {
    let body: unknown = null;
    server.use(
      http.post(api('/auth/step-up'), async ({ request }) => {
        body = await request.json();
        return (body as { code: string }).code === '000000'
          ? problem(401, 'STEP_UP_FAILED')
          : new HttpResponse(null, { status: 204 });
      }),
    );
    const onSuccess = vi.fn();
    renderUi(<StepUpModal opened onClose={() => {}} onSuccess={onSuccess} />);
    await screen.findByText('Подтвердите действие');
    fireEvent.change(screen.getByLabelText('Пароль', { selector: 'input' }), {
      target: { value: 'pw' },
    });
    fireEvent.paste(screen.getByLabelText('Цифра 1'), {
      clipboardData: { getData: () => '000000' },
    });
    await screen.findByText('Неверный пароль или код.');
    expect((screen.getByLabelText('Цифра 1') as HTMLInputElement).value).toBe('');
    fireEvent.paste(screen.getByLabelText('Цифра 1'), {
      clipboardData: { getData: () => '123456' },
    });
    await waitFor(() => expect(onSuccess).toHaveBeenCalledTimes(1));
    expect(body).toEqual({ code: '123456', password: 'pw', totp_only: false });
  });
});

describe('MoneyGuard (FR-2FA-05, DESIGN.md 8.4)', () => {
  it('без TOTP_REQUIRED — обычный блок', () => {
    renderUi(
      <MoneyGuard error={null} totpEnabled onUnlocked={() => {}} onEnroll={() => {}}>
        <span>12 345 ₽</span>
      </MoneyGuard>,
    );
    expect(screen.getByText('12 345 ₽')).toBeTruthy();
    expect(isTotpRequired(new Error('x'))).toBe(false);
  });

  it('TOTP_REQUIRED — замок вместо сумм; код «только TOTP» разблокирует без перезагрузки', async () => {
    let body: unknown = null;
    server.use(
      http.post(api('/auth/step-up'), async ({ request }) => {
        body = await request.json();
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const onUnlocked = vi.fn();
    renderUi(
      <MoneyGuard error={totpRequired} totpEnabled onUnlocked={onUnlocked} onEnroll={() => {}}>
        <span>12 345 ₽</span>
      </MoneyGuard>,
    );
    expect(screen.queryByText('12 345 ₽')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Ввести код' }));
    await screen.findByText('Подтвердите вход кодом', { selector: 'h2' });
    fireEvent.paste(screen.getByLabelText('Цифра 1'), {
      clipboardData: { getData: () => '654321' },
    });
    await waitFor(() => expect(onUnlocked).toHaveBeenCalledTimes(1));
    expect(body).toEqual({ code: '654321', totp_only: true });
  });

  it('TOTP не подключён — ссылка на подключение', () => {
    const onEnroll = vi.fn();
    renderUi(
      <MoneyGuard error={totpRequired} totpEnabled={false} onUnlocked={() => {}} onEnroll={onEnroll}>
        <span>x</span>
      </MoneyGuard>,
    );
    expect(screen.getByText(/Чтобы видеть деньги, подключите вход по коду/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Подключить' }));
    expect(onEnroll).toHaveBeenCalled();
  });
});

describe('ConfirmDialog, EmptyState, QrCode', () => {
  it('подтверждение и отмена', async () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    renderUi(
      <ConfirmDialog
        opened
        title="Удалить?"
        message="Строка уйдёт в корзину"
        confirmLabel="Удалить"
        danger
        onConfirm={onConfirm}
        onCancel={onCancel}
      />,
    );
    await screen.findByText('Строка уйдёт в корзину');
    fireEvent.click(screen.getByRole('button', { name: 'Удалить' }));
    expect(onConfirm).toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Отмена' }));
    expect(onCancel).toHaveBeenCalled();
  });

  it('пустое состояние с действием', () => {
    renderUi(<EmptyState title="Проектов нет" hint="Создайте первый" />);
    expect(screen.getByText('Проектов нет')).toBeTruthy();
    expect(screen.getByText('Создайте первый')).toBeTruthy();
  });

  it('QR: квадратная матрица из модулей, SVG без HTML-строк', () => {
    const uri = 'otpauth://totp/Estimator:i.ivanov?secret=AAAAAAAAAAAAAAAA&issuer=Estimator';
    const { size, path } = qrPath(uri);
    expect(size).toBeGreaterThanOrEqual(25);
    const cells = path.split('z').filter(Boolean);
    expect(cells.length).toBeGreaterThan(0);
    expect(cells.every((cell) => /^M\d+ \d+h1v1h-1$/.test(cell))).toBe(true);
    renderUi(<QrCode value={uri} label="QR-код" />);
    const svg = screen.getByRole('img', { name: 'QR-код' });
    expect(svg.getAttribute('viewBox')).toBe(`0 0 ${size} ${size}`);
  });
});
