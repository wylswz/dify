import type { ToolValue } from '@/app/components/workflow/block-selector/types'
import type { CommonNodeType, ModelConfig, ValueSelector } from '@/app/components/workflow/types'

export type IntentExecutorNodeType = CommonNodeType & {
  model: ModelConfig
  instruction: string
  intents: ValueSelector
  tools: ToolValue[]
  max_parallelism: number
}
