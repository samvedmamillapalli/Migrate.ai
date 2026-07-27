/**
 * Typed HTTP client for the Migration Oracle FastAPI backend.
 *
 * Base URL: NEXT_PUBLIC_API_BASE_URL, defaulting to http://127.0.0.1:8000
 * (same origin as `python scripts/dev.py restart`).
 *
 * Types are generated from the live OpenAPI spec — see `npm run gen:api`.
 */

import { resolveAuthToken } from "./clerk-token"

export const DEFAULT_API_BASE_URL = "http://127.0.0.1:8000"

export class ApiError extends Error {
  status: number
  detail: unknown

  constructor(message: string, status: number, detail: unknown) {
    super(message)
    this.name = "ApiError"
    this.status = status
    this.detail = detail
  }
}

export function apiBaseUrl(): string {
  const raw =
    (typeof process !== "undefined" &&
      process.env.NEXT_PUBLIC_API_BASE_URL?.trim()) ||
    DEFAULT_API_BASE_URL
  return raw.replace(/\/$/, "")
}

function demoApiKey(): string | undefined {
  const key =
    typeof process !== "undefined"
      ? process.env.NEXT_PUBLIC_DEMO_API_KEY?.trim()
      : undefined
  return key || undefined
}

function formatDetail(detail: unknown): string {
  if (detail == null) return "Request failed"
  if (typeof detail === "string") return detail
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        if (item && typeof item === "object" && "msg" in item) {
          return String((item as { msg: unknown }).msg)
        }
        return JSON.stringify(item)
      })
      .join("; ")
  }
  if (typeof detail === "object" && detail !== null && "detail" in detail) {
    return formatDetail((detail as { detail: unknown }).detail)
  }
  try {
    return JSON.stringify(detail)
  } catch {
    return String(detail)
  }
}

export type ApiOptions = Omit<RequestInit, "body"> & {
  body?: unknown
  /** Suppress nothing — reserved for parity with legacy quiet polls. */
  quiet?: boolean
  /** Clerk session token for API authentication */
  clerkToken?: string | null
}

export async function api<T = unknown>(
  path: string,
  options: ApiOptions = {}
): Promise<T> {
  const { body, quiet: _quiet, headers, clerkToken, ...rest } = options
  const key = demoApiKey()
  const token = clerkToken ?? (await resolveAuthToken())
  const res = await fetch(`${apiBaseUrl()}${path}`, {
    ...rest,
    headers: {
      Accept: "application/json",
      ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
      ...(key ? { "X-API-Key": key } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(headers || {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  })

  const text = await res.text()
  let parsed: unknown = null
  if (text) {
    try {
      parsed = JSON.parse(text)
    } catch {
      parsed = text
    }
  }

  if (!res.ok) {
    const detail =
      parsed &&
        typeof parsed === "object" &&
        parsed !== null &&
        "detail" in parsed
        ? (parsed as { detail: unknown }).detail
        : parsed
    throw new ApiError(formatDetail(detail), res.status, detail)
  }

  return parsed as T
}
