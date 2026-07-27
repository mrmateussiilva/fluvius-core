const API_URL = import.meta.env.VITE_API_URL || ''

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message)
  }
}

export async function http<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers)
  if (!(options.body instanceof FormData)) headers.set('Content-Type', 'application/json')

  const response = await fetch(`${API_URL}${path}`, {
    ...options,
    headers,
    credentials: 'include',
  })
  if (!response.ok) {
    const data = await response.json().catch(() => ({}))
    if (
      response.status === 401 &&
      path !== '/api/v1/auth/login' &&
      path !== '/api/v1/auth/me'
    ) {
      window.location.replace('/login?session=expired')
    }
    throw new ApiError(data.detail || 'Não foi possível concluir a operação', response.status)
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}
