/**
 * Задания выгрузки в демо (FR-EXP-05): портфель, вкладки статистики и прочие. Задание готово
 * через 1,5 с после создания, файл отдаёт общий обработчик `downloadExport`.
 */
import { uuidFrom } from "./ids";

/** Задания выгрузки демо: готовы через 1,5 с после создания. */
const jobs = new Map<
  string,
  { kind: string; createdAt: number; name: string; delay: number }
>();

/** `delay` — через сколько миллисекунд задание готово (выгрузка проекта — дольше 3 с, FR-EXP-05). */
export function createExport(kind: string, name: string, delay = 1500) {
  const id = uuidFrom(
    "export",
    kind,
    String(jobs.size + 1),
    String(Date.now()),
  );
  jobs.set(id, { kind, createdAt: Date.now(), name, delay });
  return exportJob(id);
}

export function exportJob(id: string) {
  const job = jobs.get(id);
  if (!job) return null;
  const ready = Date.now() - job.createdAt >= job.delay;
  return {
    id,
    kind: job.kind,
    status: ready ? ("ready" as const) : ("pending" as const),
    file_name: ready ? job.name : null,
    download_url: ready ? `/api/v1/exports/${id}/download` : null,
    expires_at: new Date(job.createdAt + 24 * 3600_000)
      .toISOString()
      .replace(/\.\d{3}Z$/, "Z"),
  };
}
