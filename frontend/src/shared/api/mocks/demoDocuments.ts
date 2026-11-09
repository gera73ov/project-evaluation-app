/**
 * FE-017 · документы заказчика в демо (FR-DOC-01, SPEC 11.7, `docs.png`): четыре файла «Портала
 * дилеров» как на макете и всё, что загружено за сессию. Загруженный файл «проверяется» несколько
 * секунд, потом «проверен»; имя с `eicar` — «заражён». Удаление уводит документ в корзину (demoTree).
 */
import { userRef, type DemoProject } from "./data";
import * as demoTree from "./demoTree";
import { uuidFrom } from "./ids";
import { PERSONAS } from "./personas";

export const DOC_LIMIT_BYTES = 1024 * 1024 * 1024;
export const DOC_MAX_BYTES = 50 * 1024 * 1024;
/** Сколько демо «проверяет» загруженный файл. */
const SCAN_MS = 4000;
const ALLOWED = /\.(pdf|docx|xlsx)$/i;
const MIME = new Map([
  ["pdf", "application/pdf"],
  [
    "docx",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  ],
  ["xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"],
]);

type UserRef = ReturnType<typeof userRef>;
export type DemoDocument = {
  id: string;
  file_name: string;
  mime: string;
  size_bytes: number;
  scan_status: "pending" | "clean" | "infected" | "error";
  uploaded_by: UserRef;
  uploaded_at: string;
  deleted_at: string | null;
};

type Stored = DemoDocument & { project: DemoProject; scanAt: number | null };

const MB = 1024 * 1024;
const at = (iso: string) => new Date(iso).toISOString();

function seeded(p: DemoProject): Stored[] {
  if (p.key !== "portal") return [];
  const doc = (
    key: string,
    file_name: string,
    size: number,
    scan_status: DemoDocument["scan_status"],
    by: UserRef,
    uploaded_at: string,
  ): Stored => ({
    id: uuidFrom("document", "portal", key),
    file_name,
    mime:
      MIME.get(file_name.split(".").pop() ?? "") ?? "application/octet-stream",
    size_bytes: Math.round(size * MB),
    scan_status,
    uploaded_by: by,
    uploaded_at: at(uploaded_at),
    deleted_at: null,
    project: p,
    scanAt: null,
  });
  const presale = userRef(PERSONAS.presale);
  return [
    doc(
      "tz-v3",
      "ТЗ_портал_дилеров_v3.pdf",
      4.2,
      "clean",
      presale,
      "2026-10-28T07:12:00Z",
    ),
    doc(
      "registry",
      "Реестр_интеграций.xlsx",
      0.3,
      "clean",
      userRef(PERSONAS.moderator),
      "2026-10-30T12:40:00Z",
    ),
    doc(
      "sec-req",
      "Требования_ИБ_заказчика.docx",
      1.1,
      "pending",
      presale,
      "2026-11-05T18:05:00Z",
    ),
    doc(
      "deck",
      "Презентация_заказчика.docx",
      2.7,
      "infected",
      presale,
      "2026-11-05T17:58:00Z",
    ),
  ];
}

const uploaded: Stored[] = [];
let counter = 0;

export function resetDemoDocuments(): void {
  uploaded.length = 0;
  counter = 0;
}

/** Статус с учётом «проверки» загруженного файла. */
function current(d: Stored): DemoDocument {
  const { scanAt } = d;
  const doc: DemoDocument = {
    id: d.id,
    file_name: d.file_name,
    mime: d.mime,
    size_bytes: d.size_bytes,
    scan_status: d.scan_status,
    uploaded_by: d.uploaded_by,
    uploaded_at: d.uploaded_at,
    deleted_at: d.deleted_at,
  };
  if (doc.scan_status === "pending" && scanAt !== null && Date.now() >= scanAt)
    return {
      ...doc,
      scan_status: /eicar/i.test(doc.file_name) ? "infected" : "clean",
    };
  return doc;
}

function all(p: DemoProject): DemoDocument[] {
  const base = [...seeded(p), ...uploaded.filter((d) => d.project === p)]
    .filter((d) => !demoTree.documentInTrash(p, d.id))
    .map(current);
  const ids = new Set(base.map((d) => d.id));
  const back = demoTree
    .restoredDocuments(p)
    .filter((d) => !ids.has(String(d.id))) as DemoDocument[];
  return [...base, ...back];
}

/** Занятое место: заражённые файлы не хранятся (SPEC 11.7 №3). */
function used(docs: readonly DemoDocument[]): number {
  return docs
    .filter((d) => d.scan_status !== "infected")
    .reduce((sum, d) => sum + d.size_bytes, 0);
}

/** `GET /projects/{id}/documents`. */
export function listDocuments(p: DemoProject) {
  const items = all(p).sort((a, b) =>
    a.uploaded_at.localeCompare(b.uploaded_at),
  );
  return { items, used_bytes: used(items), limit_bytes: DOC_LIMIT_BYTES };
}

type Upload = {
  file?: { file_name?: string; size_bytes?: number; mime?: string } | string;
};

/** `POST /projects/{id}/documents`: код ошибки или новый документ «проверяется». */
export function uploadDocument(
  p: DemoProject,
  raw: unknown,
  by: UserRef,
):
  | {
      error:
        | "VALIDATION_FAILED"
        | "UNSUPPORTED_MEDIA_TYPE"
        | "PAYLOAD_TOO_LARGE"
        | "PROJECT_STORAGE_LIMIT";
    }
  | DemoDocument {
  // проверка моков по контракту шлёт `{}` без файла — загружаем условный PDF
  const sent = (raw as Upload | null)?.file;
  const file =
    sent && typeof sent !== "string"
      ? sent
      : { file_name: "Документ.pdf", size_bytes: MB, mime: "application/pdf" };
  if (!file.file_name) return { error: "VALIDATION_FAILED" };
  if (!ALLOWED.test(file.file_name)) return { error: "UNSUPPORTED_MEDIA_TYPE" };
  const size = file.size_bytes ?? 0;
  if (size > DOC_MAX_BYTES) return { error: "PAYLOAD_TOO_LARGE" };
  if (used(all(p)) + size > DOC_LIMIT_BYTES)
    return { error: "PROJECT_STORAGE_LIMIT" };
  counter += 1;
  const ext = file.file_name.split(".").pop()?.toLowerCase() ?? "";
  const doc: Stored = {
    id: uuidFrom("document", "upload", String(counter), file.file_name),
    file_name: file.file_name,
    mime: MIME.get(ext) ?? file.mime ?? "application/octet-stream",
    size_bytes: size,
    scan_status: "pending",
    uploaded_by: by,
    uploaded_at: new Date().toISOString(),
    deleted_at: null,
    project: p,
    scanAt: Date.now() + SCAN_MS,
  };
  uploaded.push(doc);
  return current(doc);
}

/** `DELETE /documents/{id}`: в корзину; нет такого — false. */
export function deleteDocument(
  p: DemoProject,
  id: string,
  by: UserRef,
): boolean {
  const doc = all(p).find((d) => d.id === id);
  if (!doc) return false;
  demoTree.trashDocument(p, doc, by);
  return true;
}
