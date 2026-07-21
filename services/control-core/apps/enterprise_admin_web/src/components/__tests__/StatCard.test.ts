import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import StatCard from '../StatCard.vue'

describe('StatCard', () => {
  it('renders label and value', () => {
    const wrapper = mount(StatCard, {
      props: { label: 'Total Tasks', value: 42 },
      global: {
        stubs: {
          ElCard: {
            template: '<div data-test="card"><slot name="header" /><slot /></div>',
          },
        },
      },
    })
    expect(wrapper.text()).toContain('Total Tasks')
    expect(wrapper.text()).toContain('42')
  })

  it('renders value via slot when provided', () => {
    const wrapper = mount(StatCard, {
      props: { label: 'Test', value: 'default' },
      slots: { default: 'slotted content' },
      global: {
        stubs: {
          ElCard: {
            template: '<div><slot name="header" /><slot /></div>',
          },
        },
      },
    })
    expect(wrapper.text()).toContain('slotted content')
  })

  it('applies color style when prop is provided', () => {
    const wrapper = mount(StatCard, {
      props: { label: 'Rate', value: '85%', color: '#67c23a' },
      global: {
        stubs: {
          ElCard: {
            template: '<div><slot name="header" /><slot /></div>',
          },
        },
      },
    })
    const statValue = wrapper.find('.stat-value')
    expect(statValue.exists()).toBe(true)
    expect(statValue.attributes('style')).toContain('color')
  })

  it('does not apply color style when prop is omitted', () => {
    const wrapper = mount(StatCard, {
      props: { label: 'Count', value: 10 },
      global: {
        stubs: {
          ElCard: {
            template: '<div><slot name="header" /><slot /></div>',
          },
        },
      },
    })
    const statValue = wrapper.find('.stat-value')
    expect(statValue.attributes('style')).toBeUndefined()
  })
})
