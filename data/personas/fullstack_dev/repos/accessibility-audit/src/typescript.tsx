export type Result<T> = { ok: true; value: T } | { ok: false; error: string };

export function assertNever(x: never): never {
  throw new Error(`unexpected: ${String(x)}`);
}
