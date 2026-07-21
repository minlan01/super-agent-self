import { describe, it, expect } from 'vitest'
import { taskStatusType, extendedTaskStatusType, skillStatusType } from '../status'

describe('taskStatusType', () => {
  it('maps known statuses correctly', () => {
    expect(taskStatusType('completed')).toBe('success')
    expect(taskStatusType('failed')).toBe('danger')
    expect(taskStatusType('executing')).toBe('warning')
  })

  it('returns "info" for unknown statuses', () => {
    expect(taskStatusType('pending')).toBe('info')
    expect(taskStatusType('planning')).toBe('info')
    expect(taskStatusType('unknown')).toBe('info')
  })
})

describe('extendedTaskStatusType', () => {
  it('maps known statuses correctly', () => {
    expect(extendedTaskStatusType('completed')).toBe('success')
    expect(extendedTaskStatusType('approved')).toBe('success')
    expect(extendedTaskStatusType('failed')).toBe('danger')
    expect(extendedTaskStatusType('rejected')).toBe('danger')
    expect(extendedTaskStatusType('executing')).toBe('warning')
  })

  it('returns "info" for unknown statuses', () => {
    expect(extendedTaskStatusType('pending')).toBe('info')
  })
})

describe('skillStatusType', () => {
  it('maps known statuses correctly', () => {
    expect(skillStatusType('stable')).toBe('success')
    expect(skillStatusType('candidate')).toBe('warning')
    expect(skillStatusType('disabled')).toBe('danger')
    expect(skillStatusType('deprecated')).toBe('info')
  })

  it('returns "info" for unknown statuses', () => {
    expect(skillStatusType('unknown')).toBe('info')
  })
})
