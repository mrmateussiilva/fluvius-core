import { http } from './http'
import type { QuickReply } from './types'

export const listQuickReplies = () => http<QuickReply[]>('/api/v1/quick-replies')
export const createQuickReply = (payload: Omit<QuickReply, 'id'>) =>
  http<QuickReply>('/api/v1/quick-replies', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
