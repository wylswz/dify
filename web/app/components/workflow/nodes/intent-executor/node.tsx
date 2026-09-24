import type { FC } from 'react'
import type { IntentExecutorNodeType } from './types'
import type { NodeProps } from '@/app/components/workflow/types'
import * as React from 'react'
import { useTranslation } from 'react-i18next'
import { useTextGenerationCurrentProviderAndModelAndModelList } from '@/app/components/header/account-setting/model-provider-page/hooks'
import { ModelSelector } from '@/app/components/header/account-setting/model-provider-page/model-selector'
import { Group, GroupLabel } from '../_base/components/group'
import { ToolIcon } from '../agent/components/tool-icon'

const i18nPrefix = 'nodes.intentExecutor'

const Node: FC<NodeProps<IntentExecutorNodeType>> = ({ data }) => {
  const { t } = useTranslation(['workflow'])
  const { provider, name: modelId } = data.model || {}
  const { textGenerationModelList } = useTextGenerationCurrentProviderAndModelAndModelList()
  const hasSetModel = provider && modelId
  const enabledTools = (data.tools || []).filter((tool) => tool.enabled !== false)

  return (
    <div className="mb-1 space-y-1 px-3">
      {hasSetModel && (
        <div className="px-0 py-1">
          <ModelSelector
            value={{ provider, model: modelId }}
            models={textGenerationModelList}
            size="small"
            disabled
          />
        </div>
      )}
      {enabledTools.length > 0 && (
        <Group
          label={
            <GroupLabel className="mt-1">
              {t(($) => $[`${i18nPrefix}.tools`], { ns: 'workflow' })}
            </GroupLabel>
          }
        >
          <div className="grid grid-cols-10 gap-0.5">
            {enabledTools.map((tool) => (
              <ToolIcon
                key={`${tool.provider_name}:${tool.tool_name}`}
                id={`${tool.provider_name}:${tool.tool_name}`}
                providerName={tool.provider_name}
              />
            ))}
          </div>
        </Group>
      )}
    </div>
  )
}

export default React.memo(Node)
