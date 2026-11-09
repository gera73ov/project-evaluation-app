/** FE-020 · управляемый сокет для тестов клиента WS: открыть, прислать, разорвать. */
export class FakeSocket {
  static all: FakeSocket[] = [];
  readonly sent: Record<string, unknown>[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((message: { data: string }) => void) | null = null;
  onclose: ((event: { code: number }) => void) | null = null;
  closed = false;

  constructor(readonly url: string) {
    FakeSocket.all.push(this);
  }

  static last(): FakeSocket {
    const socket = FakeSocket.all.at(-1);
    if (!socket) throw new Error('сокет не создан');
    return socket;
  }

  static factory = (url: string): WebSocket => new FakeSocket(url) as unknown as WebSocket;

  send(data: string): void {
    this.sent.push(JSON.parse(data) as Record<string, unknown>);
  }

  close(): void {
    this.closed = true;
  }

  open(): void {
    this.onopen?.();
  }

  push(message: unknown): void {
    this.onmessage?.({ data: JSON.stringify(message) });
  }

  drop(code = 1006): void {
    this.onclose?.({ code });
  }

  /** Ответить `ack` на последнюю команду `op`. */
  ack(op: string, result: Record<string, unknown> = {}): void {
    const command = [...this.sent].reverse().find((c) => c.op === op);
    if (!command) throw new Error(`нет команды ${op}`);
    this.push({ type: 'ack', op, req_id: command.req_id, result });
  }
}
