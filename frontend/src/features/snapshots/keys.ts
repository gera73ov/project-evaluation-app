/** Ключ запроса списка снимков проекта: общий для страницы снимков, кнопки снимка, сравнения и выгрузки. */
export const snapshotsKey = (projectId: string) => ['snapshots', projectId] as const;
