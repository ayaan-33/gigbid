// Typed API client: types are GENERATED from FastAPI's OpenAPI schema (schema.d.ts, do not edit).
import createClient from "openapi-fetch";
import type { components, paths } from "./schema";

export const api = createClient<paths>({ baseUrl: "", credentials: "include" });
export type Schemas = components["schemas"];

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

/** Unwrap an openapi-fetch result or throw a readable error. */
export function ok<T>(r: { data?: T; error?: unknown; response: Response }): T {
  if (r.error !== undefined || r.data === undefined) {
    const e = r.error as { detail?: unknown } | undefined;
    const detail = typeof e?.detail === "string" ? e.detail : JSON.stringify(e?.detail ?? r.error ?? "request failed");
    throw new ApiError(r.response.status, detail);
  }
  return r.data;
}
