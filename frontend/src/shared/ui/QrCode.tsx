/**
 * FE-006 · QR-код для подключения TOTP (FR-2FA-04, DESIGN.md 10.1: 180 × 180 px). Матрица —
 * `qrcode-generator` (MIT, без зависимостей); рисуется React-SVG из модулей, без HTML-строк
 * (SEC-WEB-02) и без внешних сервисов (секрет не покидает браузер).
 */
import qrcode from 'qrcode-generator';

const QUIET = 2; // поле вокруг кода, модулей

export function qrPath(text: string): { size: number; path: string } {
  const qr = qrcode(0, 'M');
  qr.addData(text);
  qr.make();
  const count = qr.getModuleCount();
  const cells: string[] = [];
  for (let row = 0; row < count; row += 1) {
    for (let col = 0; col < count; col += 1) {
      if (qr.isDark(row, col)) cells.push(`M${col + QUIET} ${row + QUIET}h1v1h-1z`);
    }
  }
  return { size: count + QUIET * 2, path: cells.join('') };
}

export function QrCode({ value, label }: { value: string; label: string }) {
  const { size, path } = qrPath(value);
  return (
    <svg className="qr" viewBox={`0 0 ${size} ${size}`} role="img" aria-label={label} shapeRendering="crispEdges">
      <rect width={size} height={size} fill="#fff" />
      <path d={path} fill="#000" />
    </svg>
  );
}
