import type { RefObject } from 'react'
import type { IntentExecutorNodeType } from './types'
import type { Props as FormProps } from '@/app/components/workflow/nodes/_base/components/before-run-form/form'
import type { InputVar, Variable } from '@/app/components/workflow/types'
import { useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { InputVarType } from '@/app/components/workflow/types'
import useNodeCrud from '../_base/hooks/use-node-crud'

const i18nPrefix = 'nodes.intentExecutor'

type Params = {
  id: string
  payload: IntentExecutorNodeType
  runInputData: Record<string, unknown>
  runInputDataRef: RefObject<Record<string, unknown>>
  getInputVars: (textList: string[]) => InputVar[]
  setRunInputData: (data: Record<string, unknown>) => void
  toVarInputs: (variables: Variable[]) => InputVar[]
}
const useSingleRunFormParams = ({
  id,
  payload,
  runInputData,
  runInputDataRef,
  getInputVars,
  setRunInputData,
}: Params) => {
  const { t } = useTranslation(['workflow'])
  const { inputs } = useNodeCrud<IntentExecutorNodeType>(id, payload)

  const varInputs = getInputVars([inputs.instruction])

  const inputVarValues = (() => {
    const vars: Record<string, string> = {}
    Object.keys(runInputData)
      .filter((key) => !['#context#', '#files#'].includes(key))
      .forEach((key) => {
        vars[key] = runInputData[key] as string
      })
    return vars
  })()

  const setInputVarValues = useCallback(
    (newPayload: Record<string, unknown>) => {
      const newVars = {
        ...newPayload,
        '#context#': runInputDataRef.current['#context#'],
        '#files#': runInputDataRef.current['#files#'],
      }
      setRunInputData?.(newVars)
    },
    [runInputDataRef, setRunInputData],
  )

  const forms = (() => {
    const forms: FormProps[] = []

    forms.push({
      label: t(($) => $['nodes.llm.singleRun.variable'], { ns: 'workflow' })!,
      inputs: [
        {
          label: t(($) => $[`${i18nPrefix}.intents`], { ns: 'workflow' })!,
          variable: 'intents',
          type: InputVarType.paragraph,
          required: true,
        },
        ...varInputs,
      ],
      values: inputVarValues,
      onChange: setInputVarValues,
    })

    return forms
  })()

  const getDependentVars = () => {
    const promptVars = varInputs
      .map((item) => {
        // Guard against null/undefined variable to prevent app crash
        if (!item.variable || typeof item.variable !== 'string') return []

        return item.variable.slice(1, -1).split('.')
      })
      .filter((arr) => arr.length > 0)
    return [payload.intents, ...promptVars]
  }

  const getDependentVar = (variable: string) => {
    if (variable === 'intents') return payload.intents

    return false
  }

  return {
    forms,
    getDependentVars,
    getDependentVar,
  }
}

export default useSingleRunFormParams
