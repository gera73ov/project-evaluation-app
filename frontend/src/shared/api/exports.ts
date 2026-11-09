/**
 * FE-041 · выгрузки (FR-EXP-05): задание `ExportJob` → ожидание `GET /exports/{id}` до «ready» →
 * файл `GET /exports/{id}/download` с именем из задания. Общий путь для «⇩ Excel» статистики и
 * портфеля; превышение ожидания — `ExportTimeout`.
 */
import { api, type components } from './client';
import { call } from './problem';

type ExportJob = components['schemas']['ExportJob'];

export class ExportTimeout extends Error {
  constructor() {
    super('export timeout');
  }
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

export async function downloadExport(
  start: () => Promise<ExportJob>,
  { fallbackName = 'export.xlsx', interval = 1000, attempts = 60 } = {},
): Promise<void> {
  let job = await start();
  for (let i = 0; job.status !== 'ready' && i < attempts; i += 1) {
    await sleep(interval);
    const id = job.id;
    job = await call(() => api.GET('/exports/{id}', { params: { path: { id } } }));
  }
  if (job.status !== 'ready') throw new ExportTimeout();
  const id = job.id;
  const blob = await call(() => api.GET('/exports/{id}/download', { params: { path: { id } }, parseAs: 'blob' }));
  const url = URL.createObjectURL(blob as Blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = job.file_name ?? fallbackName;
  a.click();
  URL.revokeObjectURL(url);
}
