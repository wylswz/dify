import type { ValueSelector, Var } from '../../types'
import type { IntentExecutorNodeType } from './types'
import type { ToolValue } from '@/app/components/workflow/block-selector/types'
import { produce } from 'immer'
import { useCallback, useEffect } from 'react'
import { checkHasQueryBlock } from '@/app/components/base/prompt-editor/constants'
import { ModelTypeEnum } from '@/app/components/header/account-setting/model-provider-page/declarations'
import { useModelListAndDefaultModelAndCurrentProviderAndModel } from '@/app/components/header/account-setting/model-provider-page/hooks'
import useAvailableVarList from '@/app/components/workflow/nodes/_base/hooks/use-available-var-list'
import useNodeCrud from '@/app/components/workflow/nodes/_base/hooks/use-node-crud'
import { AppModeEnum } from '@/types/app'
import { useIsChatMode, useNodesReadOnly } from '../../hooks/use-workflow'
import { VarType } from '../../types'

const useConfig = (id: string, payload: IntentExecutorNodeType) => {
  const { nodesReadOnly: readOnly } = useNodesReadOnly()
  const isChatMode = useIsChatMode()

  const { inputs, setInputs } = useNodeCrud<IntentExecutorNodeType>(id, payload)

  const filterIntentsVar = useCallback((varPayload: Var) => {
    const intentVariableTypes: readonly VarType[] = [VarType.string, VarType.arrayString]
    return intentVariableTypes.includes(varPayload.type)
  }, [])

  const filterInputVar = useCallback((varPayload: Var) => {
    const scalarVariableTypes: readonly VarType[] = [VarType.number, VarType.string]
    return scalarVariableTypes.includes(varPayload.type)
  }, [])

  const { availableVars, availableNodesWithParent } = useAvailableVarList(id, {
    onlyLeafNodeVar: false,
    filterVar: filterInputVar,
  })

  const handleIntentsChange = useCallback(
    (newIntents: ValueSelector | string) => {
      const newInputs = produce(inputs, (draft) => {
        draft.intents = (newIntents as ValueSelector) || []
      })
      setInputs(newInputs)
    },
    [inputs, setInputs],
  )

  // model
  const model = inputs.model || {
    provider: '',
    name: '',
    mode: AppModeEnum.CHAT,
    completion_params: {
      temperature: 0.7,
    },
  }
  const isChatModel = model.mode === AppModeEnum.CHAT

  const { currentProvider, currentModel } = useModelListAndDefaultModelAndCurrentProviderAndModel(
    ModelTypeEnum.textGeneration,
  )

  const handleModelChanged = useCallback(
    (model: { provider: string; modelId: string; mode?: string }) => {
      const newInputs = produce(inputs, (draft) => {
        draft.model.provider = model.provider
        draft.model.name = model.modelId
        draft.model.mode = model.mode!
      })
      setInputs(newInputs)
    },
    [inputs, setInputs],
  )

  useEffect(() => {
    if (currentProvider?.provider && currentModel?.model && !model.provider) {
      handleModelChanged({
        provider: currentProvider.provider,
        modelId: currentModel.model,
        mode: currentModel.model_properties?.mode as string,
      })
    }
  }, [model?.provider, currentProvider, currentModel, handleModelChanged])

  const handleCompletionParamsChange = useCallback(
    (newParams: Record<string, unknown>) => {
      const newInputs = produce(inputs, (draft) => {
        draft.model.completion_params = newParams
      })
      setInputs(newInputs)
    },
    [inputs, setInputs],
  )

  const handleInstructionChange = useCallback(
    (newInstruction: string) => {
      const newInputs = produce(inputs, (draft) => {
        draft.instruction = newInstruction
      })
      setInputs(newInputs)
    },
    [inputs, setInputs],
  )

  const handleToolsChange = useCallback(
    (newTools: ToolValue[]) => {
      const newInputs = produce(inputs, (draft) => {
        draft.tools = newTools
      })
      setInputs(newInputs)
    },
    [inputs, setInputs],
  )

  const handleMaxParallelismChange = useCallback(
    (newMaxParallelism: number) => {
      const newInputs = produce(inputs, (draft) => {
        draft.max_parallelism = newMaxParallelism
      })
      setInputs(newInputs)
    },
    [inputs, setInputs],
  )

  const hasSetBlockStatus = {
    history: false,
    query: isChatMode ? checkHasQueryBlock(inputs.instruction) : false,
    context: false,
  }

  return {
    readOnly,
    inputs,
    filterIntentsVar,
    handleIntentsChange,
    isChatModel,
    isChatMode,
    handleModelChanged,
    handleCompletionParamsChange,
    handleInstructionChange,
    handleToolsChange,
    handleMaxParallelismChange,
    hasSetBlockStatus,
    availableVars,
    availableNodesWithParent,
  }
}

export default useConfig
