const AUTH_TOKEN_KEY = 'interview-simulator-auth-token'
const AUTH_EVENT = 'interview-auth-changed'

export function getStoredAuthToken(): string | null {
  return window.localStorage.getItem(AUTH_TOKEN_KEY)
}

export function setStoredAuthToken(token: string): void {
  window.localStorage.setItem(AUTH_TOKEN_KEY, token)
  window.dispatchEvent(new Event(AUTH_EVENT))
}

export function clearStoredAuthToken(): void {
  window.localStorage.removeItem(AUTH_TOKEN_KEY)
  window.dispatchEvent(new Event(AUTH_EVENT))
}

export { AUTH_EVENT }
