export function normalizeText(value: string): string {
  return value.toLowerCase().trim().replace(/\s+/g, ' ');
}
