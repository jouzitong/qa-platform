export function parseJson<T>(text: string, label: string): T {
  try {
    return JSON.parse(text) as T
  } catch {
    throw new Error(`${label} 不是有效的 JSON`)
  }
}

export function pretty(value: unknown): string {
  return JSON.stringify(value, null, 2)
}

export function shortId(value: string): string {
  return value.slice(0, 8)
}
