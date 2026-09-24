import type { TFunction } from 'i18next'
import type { NodeDefault } from '../../types'
import type { IntentExecutorNodeType } from './types'
import { BlockClassification } from '@/app/components/workflow/block-selector/types'
import { BlockEnum } from '@/app/components/workflow/types'
import { genNodeMetaData } from '@/app/components/workflow/utils'
import { AppModeEnum } from '@/types/app'

const i18nPrefix = ''

const metaData = genNodeMetaData({
  classification: BlockClassification.Default,
  sort: 3.1,
  type: BlockEnum.IntentExecutor,
})
const nodeDefault: NodeDefault<IntentExecutorNodeType> = {
  metaData,
  defaultValue: {
    intents: [],
    model: {
      provider: '',
      name: '',
      mode: AppModeEnum.CHAT,
      completion_params: {
        temperature: 0.7,
      },
    },
    instruction: '',
    tools: [],
    max_parallelism: 4,
  },
  checkValid(payload: IntentExecutorNodeType, t: TFunction<['workflow']>) {
    let errorMessages = ''
    if (!errorMessages && (!payload.intents || payload.intents.length === 0))
      errorMessages = t(($) => $[`${i18nPrefix}errorMsg.fieldRequired`], {
        ns: 'workflow',
        field: t(($) => $[`${i18nPrefix}nodes.intentExecutor.intents`], { ns: 'workflow' }),
      })

    if (!errorMessages && !payload.model.provider)
      errorMessages = t(($) => $[`${i18nPrefix}errorMsg.fieldRequired`], {
        ns: 'workflow',
        field: t(($) => $[`${i18nPrefix}errorMsg.fields.model`], { ns: 'workflow' }),
      })

    if (!errorMessages && !(payload.tools || []).some((tool) => tool.enabled !== false))
      errorMessages = t(($) => $[`${i18nPrefix}errorMsg.fieldRequired`], {
        ns: 'workflow',
        field: t(($) => $[`${i18nPrefix}nodes.intentExecutor.tools`], { ns: 'workflow' }),
      })

    return {
      isValid: !errorMessages,
      errorMessage: errorMessages,
    }
  },
}
export default nodeDefault
