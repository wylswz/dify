import type { Node } from '@/app/components/workflow/types'
import {
  getNodeOutputVars,
  getNodeUsedVars,
  toNodeOutputVars,
} from '@/app/components/workflow/nodes/_base/components/variable/utils'
import { BlockEnum } from '@/app/components/workflow/types'

const createNode = (): Node =>
  ({
    id: 'intent-node-1',
    data: {
      title: 'Intent Executor',
      type: BlockEnum.IntentExecutor,
      intents: ['start', 'intents'],
      instruction: 'Route {{#start.query#}} to a tool',
      tools: [],
      max_parallelism: 4,
    },
  }) as unknown as Node

describe('intent-executor variable utils', () => {
  it('exposes results, files, and usage as output vars', () => {
    const output = toNodeOutputVars([createNode()], false, () => true, [], [], [], {})[0]

    expect(output?.vars.map((v) => v.variable)).toEqual(['results', 'files', 'usage'])
    expect(output?.vars.map((v) => v.type)).toEqual(['array[object]', 'array[file]', 'object'])
  })

  it('exposes the three output selectors for downstream nodes', () => {
    expect(getNodeOutputVars(createNode(), false)).toEqual([
      ['intent-node-1', 'results'],
      ['intent-node-1', 'files'],
      ['intent-node-1', 'usage'],
    ])
  })

  it('collects the intents selector and instruction template vars as used vars', () => {
    const used = getNodeUsedVars(createNode())

    expect(used).toContainEqual(['start', 'intents'])
    expect(used).toContainEqual(['start', 'query'])
  })
})
