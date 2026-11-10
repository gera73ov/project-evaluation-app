/**
 * Сохранить файл из памяти под заданным именем: временная ссылка `blob:` и щелчок по ней.
 * Ссылку отзываем не сразу: браузер начинает скачивание уже после `click()`, и при немедленном
 * отзыве файл сохраняется без имени («download») или не сохраняется вовсе.
 */
export const REVOKE_DELAY_MS = 60_000;

export function saveBlob(blob: Blob, name: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), REVOKE_DELAY_MS);
}
