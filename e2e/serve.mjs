/**
 * FE-090 · локальная замена Nginx стенда для Playwright, когда Docker недоступен.
 *
 * Делает то же, что deploy/nginx/conf.d/estimator.conf в части, важной для UI: HTTPS, статика
 * frontend/dist, index.html для маршрутов SPA со свежим nonce в CSP и в <meta name="csp-nonce">,
 * прокси /api на API (по умолчанию http://127.0.0.1:8000) с X-Forwarded-*. WebSocket не нужен
 * сценариям входа. Сертификат — самоподписанный, в E2E_TLS_DIR; если его нет, создаётся через openssl.
 *
 * Только для тестов: на dev-стенде сценарии идут через настоящий Nginx (E2E_BASE_URL).
 */
import { execFileSync } from 'node:child_process';
import { randomBytes } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, statSync } from 'node:fs';
import http from 'node:http';
import https from 'node:https';
import { extname, join, normalize, resolve } from 'node:path';

const ROOT = resolve(process.env.E2E_DIST ?? new URL('../frontend/dist', import.meta.url).pathname);
const API = new URL(process.env.E2E_API_URL ?? 'http://127.0.0.1:8000');
const PORT = Number(process.env.E2E_PORT ?? 8443);
const TLS = process.env.E2E_TLS_DIR ?? new URL('./.tls', import.meta.url).pathname;

const TYPES = new Map([
  ['.js', 'text/javascript'],
  ['.css', 'text/css'],
  ['.svg', 'image/svg+xml'],
  ['.png', 'image/png'],
  ['.woff2', 'font/woff2'],
  ['.ico', 'image/x-icon'],
]);

const SECURITY = {
  'X-Content-Type-Options': 'nosniff',
  'Referrer-Policy': 'no-referrer',
  'Strict-Transport-Security': 'max-age=31536000',
};

function csp(nonce) {
  return (
    "default-src 'self'; script-src 'self'; " +
    `style-src 'self' 'nonce-${nonce}'; img-src 'self' data:; connect-src 'self'; ` +
    "frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'"
  );
}

function sendIndex(res) {
  const nonce = randomBytes(16).toString('hex');
  const html = readFileSync(join(ROOT, 'index.html'), 'utf8').replaceAll('__CSP_NONCE__', nonce);
  res.writeHead(200, {
    ...SECURITY,
    'Content-Type': 'text/html; charset=utf-8',
    'Cache-Control': 'no-store',
    'Content-Security-Policy': csp(nonce),
  });
  res.end(html);
}

function sendStatic(path, res) {
  const file = normalize(join(ROOT, path));
  if (!file.startsWith(ROOT) || !existsSync(file) || !statSync(file).isFile()) return false;
  res.writeHead(200, {
    ...SECURITY,
    'Content-Type': TYPES.get(extname(file)) ?? 'application/octet-stream',
    'Content-Security-Policy': "default-src 'none'; frame-ancestors 'none'",
  });
  res.end(readFileSync(file));
  return true;
}

function proxy(req, res) {
  const upstream = http.request(
    {
      host: API.hostname,
      port: API.port,
      method: req.method,
      path: req.url,
      headers: {
        ...req.headers,
        host: req.headers.host,
        'x-forwarded-for': req.socket.remoteAddress ?? '',
        'x-forwarded-proto': 'https',
        'x-real-ip': req.socket.remoteAddress ?? '',
      },
    },
    (answer) => {
      res.writeHead(answer.statusCode ?? 502, answer.headers);
      answer.pipe(res);
    },
  );
  upstream.on('error', () => {
    res.writeHead(502, { 'Content-Type': 'application/problem+json' });
    res.end(JSON.stringify({ status: 502, code: 'SERVICE_UNAVAILABLE', title: 'API недоступен' }));
  });
  req.pipe(upstream);
}

function ensureCertificate() {
  if (existsSync(join(TLS, 'server.key')) && existsSync(join(TLS, 'server.crt'))) return;
  mkdirSync(TLS, { recursive: true });
  // prettier-ignore
  execFileSync('openssl', [
    'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '30', '-subj', '/CN=localhost',
    '-addext', 'subjectAltName=DNS:localhost,IP:127.0.0.1',
    '-keyout', join(TLS, 'server.key'), '-out', join(TLS, 'server.crt'),
  ], { stdio: 'ignore' });
}

ensureCertificate();

const server = https.createServer(
  { key: readFileSync(join(TLS, 'server.key')), cert: readFileSync(join(TLS, 'server.crt')) },
  (req, res) => {
    const path = new URL(req.url ?? '/', 'https://local').pathname;
    if (path.startsWith('/api/') || path.startsWith('/health')) return proxy(req, res);
    if (path !== '/' && path !== '/index.html' && sendStatic(path, res)) return undefined;
    return sendIndex(res);
  },
);

server.listen(PORT, '127.0.0.1', () => {
  console.log(`e2e: https://localhost:${PORT} → ${ROOT}, API ${API.href}`);
});
