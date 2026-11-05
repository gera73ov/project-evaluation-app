/**
 * FE-001 · контракты, на которых стоят моки: OpenAPI (API-002), матрица прав (SEC-001),
 * события WebSocket (RT-001). Файлы читаются прямо из contracts/, поэтому моки не расходятся
 * с контрактом: изменился контракт — изменились ответы, а тест mocks.test.ts это проверит.
 */
import { parse } from 'yaml';

import openapiText from '../../../../../contracts/openapi.yaml?raw';
import permissionsText from '../../../../../contracts/permissions.yaml?raw';
import wsEventsSchema from '../../../../../contracts/ws-events.schema.json';

export type Schema = {
  $ref?: string;
  type?: string | string[];
  properties?: Record<string, Schema>;
  required?: string[];
  items?: Schema;
  anyOf?: Schema[];
  oneOf?: Schema[];
  allOf?: Schema[];
  enum?: unknown[];
  const?: unknown;
  format?: string;
  pattern?: string;
  minimum?: number;
  maximum?: number;
  minLength?: number;
  maxLength?: number;
  minItems?: number;
  maxItems?: number;
  additionalProperties?: boolean | Schema;
  [key: string]: unknown;
};

type Parameter = { name: string; in: string; required?: boolean; schema?: Schema };
type Response = { $ref?: string; content?: Record<string, { schema?: Schema }> };

export type Operation = {
  operationId: string;
  method: 'get' | 'post' | 'put' | 'patch' | 'delete';
  path: string;
  permission: string[];
  parameters: Parameter[];
  responses: Record<string, Response>;
};

type OpenApiDoc = {
  paths: Record<string, Record<string, unknown>>;
  components: { schemas: Record<string, Schema>; responses: Record<string, Response> };
};

export const openapi = parse(openapiText) as OpenApiDoc;
export const wsSchema = wsEventsSchema as unknown as Schema & { $defs: Record<string, Schema> };

const METHODS = ['get', 'post', 'put', 'patch', 'delete'] as const;

/** Все HTTP-операции OpenAPI (WebSocket /ws — отдельно, см. ws.ts). */
export const operations: Operation[] = Object.entries(openapi.paths).flatMap(([path, item]) =>
  METHODS.filter((m) => item[m]).map((method) => {
    const op = item[method] as Record<string, unknown>;
    const permission = op['x-permission'];
    return {
      operationId: String(op.operationId),
      method,
      path,
      permission: Array.isArray(permission) ? permission.map(String) : [String(permission)],
      parameters: [
        ...((item.parameters as Parameter[] | undefined) ?? []),
        ...((op.parameters as Parameter[] | undefined) ?? []),
      ],
      responses: op.responses as Record<string, Response>,
    };
  }),
);

/** Схема по ссылке `#/components/schemas/X` или `#/$defs/X` (для схемы WS). */
export function resolveRef(ref: string): Schema {
  const [doc, pointer] = ref.startsWith('#/$defs/') ? [wsSchema, ref] : [openapi, ref];
  const target = pointer
    .slice(2)
    .split('/')
    .reduce<unknown>((node, key) => (node as Record<string, unknown>)?.[key], doc);
  if (!target) throw new Error(`нет схемы ${ref}`);
  return target as Schema;
}

/** Ответ с раскрытым `$ref` на components/responses. */
export function resolveResponse(response: Response): Response {
  return response.$ref ? (resolveRef(response.$ref) as Response) : response;
}

/** Первый успешный ответ операции: код и схема тела (null — тела нет, «binary» — файл). */
export function successResponse(op: Operation): {
  status: number;
  schema: Schema | null;
  binary: boolean;
} {
  const code = Object.keys(op.responses).find((c) => c.startsWith('2')) ?? '200';
  const response = resolveResponse(op.responses[code] ?? {});
  const json = response.content?.['application/json']?.schema;
  const binary = Boolean(response.content && !json);
  return { status: Number(code), schema: json ?? null, binary };
}

/** Путь OpenAPI → шаблон MSW для любого origin: `/projects/{id}` → `<origin>/api/v1/projects/:id`. */
export function mswPath(path: string, base = '*/api/v1'): string {
  return base + path.replace(/\{([^}]+)\}/g, ':$1');
}

// --- матрица прав --------------------------------------------------------------------------

export type Grant = {
  permission?: string;
  inherit?: string;
  context?: string;
  unless_role?: string[];
  requires_system_role?: string;
  requires_setting?: string;
};

type PermissionsDoc = {
  permissions: Record<string, { totp_gate?: boolean; money_fields?: boolean }>;
  grants: Record<string, Grant[]>;
};

export const permissionsDoc = parse(permissionsText) as PermissionsDoc;

/** Псевдоправа без роли: в моках пользователь всегда вошёл и прошёл TOTP. */
export const PSEUDO_PERMISSIONS = new Set([
  'public',
  'authenticated',
  'session.pre_mfa',
  'token.login_step',
  'token.activation',
]);
