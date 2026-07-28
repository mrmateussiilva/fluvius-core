import { http } from './http'
import type { OperationalHealth } from './types'

export const getOperationalHealth = () =>
  http<OperationalHealth>('/api/v1/operations/health')
