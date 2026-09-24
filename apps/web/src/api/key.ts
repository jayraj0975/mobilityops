/** The optional API key of a self-hosted server, kept in this browser only. */
const STORAGE_KEY = "mobilityops.apiKey";

export function getApiKey(): string {
  try {
    return window.localStorage.getItem(STORAGE_KEY) ?? "";
  } catch {
    return ""; // storage can be blocked (private windows); the app then simply sends no key
  }
}

export function setApiKey(value: string): void {
  try {
    const key = value.trim();
    if (key) window.localStorage.setItem(STORAGE_KEY, key);
    else window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    /* ignore: nothing useful to do if storage is unavailable */
  }
}

/** Headers every API request carries; includes the key only when one has been entered. */
export function authHeaders(): Record<string, string> {
  const key = getApiKey();
  return key ? { "X-API-Key": key } : {};
}
