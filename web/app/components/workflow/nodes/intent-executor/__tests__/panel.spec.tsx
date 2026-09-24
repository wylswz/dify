import type { IntentExecutorNodeType } from '../types'
import type { PanelProps } from '@/types/workflow'
import { render, screen } from '@testing-library/react'
import { BlockEnum } from '@/app/components/workflow/types'
import { AppModeEnum } from '@/types/app'
import Panel from '../panel'
import useConfig from '../use-config'

vi.mock(
  '@/app/components/header/account-setting/model-provider-page/model-parameter-modal',
  () => ({
    __esModule: true,
    default: () => <div>model-parameter-modal</div>,
  }),
)

vi.mock('@/app/components/workflow/nodes/_base/components/variable/var-reference-picker', () => ({
  __esModule: true,
  default: () => <div>intents-var-picker</div>,
}))

vi.mock('@/app/components/workflow/nodes/_base/components/prompt/editor', () => ({
  __esModule: true,
  default: () => <div>instruction-editor</div>,
}))

vi.mock('@/app/components/plugins/plugin-detail-panel/multiple-tool-selector', () => ({
  __esModule: true,
  default: () => <div>multiple-tool-selector</div>,
}))

vi.mock('@/app/components/workflow/nodes/_base/components/input-number-with-slider', () => ({
  __esModule: true,
  default: () => <div>max-parallelism-slider</div>,
}))

vi.mock('@/app/components/workflow/nodes/_base/components/output-vars', () => ({
  __esModule: true,
  default: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  VarItem: ({ name, type }: { name: string; type: string }) => <div>{`${name}:${type}`}</div>,
}))

vi.mock('../use-config', () => ({
  __esModule: true,
  default: vi.fn(),
}))

const mockUseConfig = vi.mocked(useConfig)

const createData = (overrides: Partial<IntentExecutorNodeType> = {}): IntentExecutorNodeType => ({
  title: 'Intent Executor',
  desc: '',
  type: BlockEnum.IntentExecutor,
  model: {
    provider: 'langgenius/openai/openai',
    name: 'gpt-4o',
    mode: AppModeEnum.CHAT,
    completion_params: {},
  } as IntentExecutorNodeType['model'],
  intents: ['start', 'intents'],
  instruction: 'Pick a tool per intent',
  tools: [
    {
      provider_name: 'langgenius/search/search',
      tool_name: 'search',
      tool_label: 'Search',
      enabled: true,
    },
  ],
  max_parallelism: 4,
  ...overrides,
})

const panelProps = {} as PanelProps

describe('intent-executor/panel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockUseConfig.mockReturnValue({
      readOnly: false,
      inputs: createData(),
      filterIntentsVar: vi.fn(() => true),
      handleIntentsChange: vi.fn(),
      isChatModel: true,
      isChatMode: true,
      handleModelChanged: vi.fn(),
      handleCompletionParamsChange: vi.fn(),
      handleInstructionChange: vi.fn(),
      handleToolsChange: vi.fn(),
      handleMaxParallelismChange: vi.fn(),
      hasSetBlockStatus: { history: false, query: false, context: false },
      availableVars: [],
      availableNodesWithParent: [],
    } as ReturnType<typeof useConfig>)
  })

  it('renders all config sections and the three output vars', () => {
    render(<Panel id="node-1" data={createData()} panelProps={panelProps} />)

    expect(screen.getByText('model-parameter-modal')).toBeInTheDocument()
    expect(screen.getByText('intents-var-picker')).toBeInTheDocument()
    expect(screen.getByText('instruction-editor')).toBeInTheDocument()
    expect(screen.getByText('multiple-tool-selector')).toBeInTheDocument()
    expect(screen.getByText('max-parallelism-slider')).toBeInTheDocument()
    expect(screen.getByText('results:array[object]')).toBeInTheDocument()
    expect(screen.getByText('files:array[file]')).toBeInTheDocument()
    expect(screen.getByText('usage:object')).toBeInTheDocument()
  })
})
