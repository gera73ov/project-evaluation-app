/**
 * Бюджет входов с одного IP для сценариев: сервер пускает 20 попыток в минуту (вход и код TOTP
 * считаются вместе, FR-LOCK-02), после чего блокирует IP на 5 минут. Все сценарии идут в одном
 * процессе (workers: 1), поэтому общий счётчик модуля видит входы всех файлов; перед входом
 * сценарий ждёт, пока за последние 60 с не освободится место. Запас — две попытки.
 */
const WINDOW_MS = 60_000;
const LIMIT = 18;
const spent: number[] = [];

/** Дождаться места для `hits` попыток (вход с TOTP — две) и записать их. */
export async function spendLogin(hits = 2): Promise<void> {
  for (;;) {
    const now = Date.now();
    while (spent.length && (spent[0] ?? now) <= now - WINDOW_MS) spent.shift();
    if (spent.length + hits <= LIMIT) break;
    await new Promise((resolve) => setTimeout(resolve, (spent[0] ?? now) + WINDOW_MS - now + 50));
  }
  const at = Date.now();
  for (let i = 0; i < hits; i++) spent.push(at);
}
