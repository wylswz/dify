import type { IntentExecutorNodeType } from '../types'
import { withSelectorKey } from '@/test/i18n-mock'
import { AppModeEnum } from '@/types/app'
import { BlockEnum } from '../../../types'
import nodeDefault from '../default'

const t = withSelectorKey((key: string) => key, 'workflow')

const createPayload = (overrides: Partial<IntentExecutorNodeType> = {}): IntentExecutorNodeType =>
  ({
    ...nodeDefault.defaultValue,
    type: BlockEnum.IntentExecutor,
    intents: ['start', 'intents'],
    model: {
      provider: 'langgenius/openai/openai',
      name: 'gpt-4o',
      mode: AppModeEnum.CHAT,
      completion_params: { temperature: 0.7 },
    },
    tools: [
      {
        provider_name: 'langgenius/search/search',
        tool_name: 'search',
        tool_label: 'Search',
        enabled: true,
      },
    ],
    ...overrides,
  }) as IntentExecutorNodeType

describe('intent-executor default node validation', () => {
  it('requires an intents variable', () => {
    const result = nodeDefault.checkValid(createPayload({ intents: [] }), t)

    expect(result.isValid).toBe(false)
    expect(result.errorMessage).toBe('errorMsg.fieldRequired')
  })

  it('requires a model provider', () => {
    const result = nodeDefault.checkValid(
      createPayload({
        model: { provider: '', name: '', mode: AppModeEnum.CHAT, completion_params: {} },
      }),
      t,
    )

    expect(result.isValid).toBe(false)
    expect(result.errorMessage).toBe('errorMsg.fieldRequired')
  })

  it('requires at least one tool', () => {
    const result = nodeDefault.checkValid(createPayload({ tools: [] }), t)

    expect(result.isValid).toBe(false)
    expect(result.errorMessage).toBe('errorMsg.fieldRequired')
  })

  it('rejects a tool list where every tool is disabled', () => {
    const result = nodeDefault.checkValid(
      createPayload({
        tools: [
          {
            provider_name: 'langgenius/search/search',
            tool_name: 'search',
            tool_label: 'Search',
            enabled: false,
          },
          {
            provider_name: 'langgenius/weather/weather',
            tool_name: 'weather',
            tool_label: 'Weather',
            enabled: false,
          },
        ],
      }),
      t,
    )

    expect(result.isValid).toBe(false)
    expect(result.errorMessage).toBe('errorMsg.fieldRequired')
  })

  it('is valid with intents, model, and one enabled tool', () => {
    const result = nodeDefault.checkValid(createPayload(), t)

    expect(result.isValid).toBe(true)
    expect(result.errorMessage).toBe('')
  })

  it('is valid when one disabled tool exists alongside an enabled one', () => {
    const result = nodeDefault.checkValid(
      createPayload({
        tools: [
          {
            provider_name: 'langgenius/search/search',
            tool_name: 'search',
            tool_label: 'Search',
            enabled: true,
          },
          {
            provider_name: 'langgenius/weather/weather',
            tool_name: 'weather',
            tool_label: 'Weather',
            enabled: false,
          },
        ],
      }),
      t,
    )

    expect(result.isValid).toBe(true)
  })
})
