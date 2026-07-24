const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message)
  }
}

export async function http<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = localStorage.getItem('fluvius_token')
  const headers = new Headers(options.headers)
  if (!(options.body instanceof FormData)) headers.set('Content-Type', 'application/json')
  if (token) headers.set('Authorization', `Bearer ${token}`)

  const response = await fetch(`${API_URL}${path}`, { ...options, headers })
  if (!response.ok) {
    const data = await response.json().catch(() => ({}))
    if (response.status === 401 && path !== '/api/v1/auth/login') {
      localStorage.removeItem('fluvius_token')
      window.location.replace('/login?session=expired')
    }
    throw new ApiError(data.detail || 'Não foi possível concluir a operação', response.status)
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}
