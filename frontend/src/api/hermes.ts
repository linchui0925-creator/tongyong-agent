/**
 * Hermes API — MEMORY.md / USER.md / Skills flat-file CRUD
 */
const BASE = '/api/hermes'

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`Hermes API error ${res.status}: ${text}`)
  }
  return res.json()
}

// ── MEMORY.md ──

export interface MemoryFileData {
  content: string
  stats: {
    entry_count: number
    char_count: number
    max_chars: number
    file_path: string
  }
}

export async function getMemory(): Promise<MemoryFileData> {
  return request(`${BASE}/memory`)
}

export async function writeMemory(content: string) {
  return request(`${BASE}/memory`, {
    method: 'POST',
    body: JSON.stringify({ content }),
  })
}

export interface EntryListResponse {
  entries: string[]
  target: string
}

export async function listMemoryEntries(): Promise<EntryListResponse> {
  return request(`${BASE}/memory/entries`)
}

export async function addMemoryEntry(entry: string) {
  return request(`${BASE}/memory/entries`, {
    method: 'POST',
    body: JSON.stringify({ entry }),
  })
}

export async function replaceMemoryEntry(old: string, entry: string) {
  return request(`${BASE}/memory/entries`, {
    method: 'PUT',
    body: JSON.stringify({ old, new: entry }),
  })
}

export async function deleteMemoryEntry(entry: string) {
  return request(`${BASE}/memory/entries?old=${encodeURIComponent(entry)}`, {
    method: 'DELETE',
  })
}

// ── USER.md ──

export async function getUser(): Promise<MemoryFileData> {
  return request(`${BASE}/user`)
}

export async function writeUser(content: string) {
  return request(`${BASE}/user`, {
    method: 'POST',
    body: JSON.stringify({ content }),
  })
}

export async function listUserEntries(): Promise<EntryListResponse> {
  return request(`${BASE}/user/entries`)
}

export async function addUserEntry(entry: string) {
  return request(`${BASE}/user/entries`, {
    method: 'POST',
    body: JSON.stringify({ entry }),
  })
}

export async function replaceUserEntry(old: string, entry: string) {
  return request(`${BASE}/user/entries`, {
    method: 'PUT',
    body: JSON.stringify({ old, new: entry }),
  })
}

export async function deleteUserEntry(entry: string) {
  return request(`${BASE}/user/entries?old=${encodeURIComponent(entry)}`, {
    method: 'DELETE',
  })
}

// ── Stats ──

export interface HermesStats {
  memory: {
    entry_count: number
    char_count: number
    max_chars: number
  }
  user: {
    entry_count: number
    char_count: number
    max_chars: number
  }
}

export async function getHermesStats(): Promise<HermesStats> {
  return request(`${BASE}/stats`)
}
