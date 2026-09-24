import type { FC } from 'react'
import type { IntentExecutorNodeType } from './types'
import type { NodePanelProps } from '@/app/components/workflow/types'
import { Infotip, InfotipContent, InfotipTrigger } from '@langgenius/dify-ui/infotip'
import * as React from 'react'
import { useTranslation } from 'react-i18next'
import ModelParameterModal from '@/app/components/header/account-setting/model-provider-page/model-parameter-modal'
import MultipleToolSelector from '@/app/components/plugins/plugin-detail-panel/multiple-tool-selector'
import Field from '@/app/components/workflow/nodes/_base/components/field'
import InputNumberWithSlider from '@/app/components/workflow/nodes/_base/components/input-number-with-slider'
import OutputVars, { VarItem } from '@/app/components/workflow/nodes/_base/components/output-vars'
import Split from '@/app/components/workflow/nodes/_base/components/split'
import Editor from '../_base/components/prompt/editor'
import VarReferencePicker from '../_base/components/variable/var-reference-picker'
import useConfig from './use-config'

const i18nPrefix = 'nodes.intentExecutor'
const i18nCommonPrefix = 'common'

const Panel: FC<NodePanelProps<IntentExecutorNodeType>> = ({ id, data }) => {
  const instructionLabelId = React.useId()

  const { t } = useTranslation(['workflow'])

  const {
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
  } = useConfig(id, data)

  const model = inputs.model

  return (
    <div className="pt-2">
      <div className="space-y-4 px-4">
        <Field title={t(($) => $[`${i18nCommonPrefix}.model`], { ns: 'workflow' })} required>
          <ModelParameterModal
            popupClassName="w-[387px]!"
            isInWorkflow
            isAdvancedMode={true}
            provider={model?.provider}
            completionParams={model?.completion_params}
            modelId={model?.name}
            setModel={handleModelChanged}
            onCompletionParamsChange={handleCompletionParamsChange}
            hideDebugWithMultipleModel
            debugWithMultipleModel={false}
            readonly={readOnly}
            nodesOutputVars={availableVars}
            availableNodes={availableNodesWithParent}
          />
        </Field>
        <Field title={t(($) => $[`${i18nPrefix}.intents`], { ns: 'workflow' })} required>
          <VarReferencePicker
            readonly={readOnly}
            nodeId={id}
            isShowNodeName
            value={inputs.intents || []}
            onChange={handleIntentsChange}
            filterVar={filterIntentsVar}
          />
        </Field>
        <Split />
        <Editor
          title={
            <div className="flex items-center space-x-1">
              <span id={instructionLabelId} className="uppercase">
                {t(($) => $[`${i18nPrefix}.instruction`], { ns: 'workflow' })}
              </span>
              <Infotip>
                <InfotipTrigger aria-labelledby={instructionLabelId} className="ml-0.5 size-3.5" />
                <InfotipContent aria-labelledby={instructionLabelId} className="w-30">
                  {t(($) => $[`${i18nPrefix}.instructionTip`], { ns: 'workflow' })}
                </InfotipContent>
              </Infotip>
            </div>
          }
          value={inputs.instruction}
          onChange={handleInstructionChange}
          readOnly={readOnly}
          isChatModel={isChatModel}
          isChatApp={isChatMode}
          isShowContext={false}
          hasSetBlockStatus={hasSetBlockStatus}
          nodesOutputVars={availableVars}
          availableNodes={availableNodesWithParent}
        />
        <MultipleToolSelector
          disabled={readOnly}
          nodeId={id}
          nodeOutputVars={availableVars}
          availableNodes={availableNodesWithParent}
          label={t(($) => $[`${i18nPrefix}.tools`], { ns: 'workflow' })}
          required
          tooltip={t(($) => $[`${i18nPrefix}.toolsTip`], { ns: 'workflow' })}
          value={inputs.tools || []}
          onChange={handleToolsChange}
          supportCollapse
        />
        <InputNumberWithSlider
          label={t(($) => $[`${i18nPrefix}.maxParallelism`], { ns: 'workflow' })}
          min={1}
          max={16}
          value={inputs.max_parallelism}
          readonly={readOnly}
          onChange={handleMaxParallelismChange}
        />
      </div>
      <Split />
      <div>
        <OutputVars>
          <>
            <VarItem
              name="results"
              type="array[object]"
              description={t(($) => $[`${i18nPrefix}.outputVars.results`], { ns: 'workflow' })}
            />
            <VarItem
              name="files"
              type="array[file]"
              description={t(($) => $[`${i18nPrefix}.outputVars.files`], { ns: 'workflow' })}
            />
            <VarItem
              name="usage"
              type="object"
              description={t(($) => $[`${i18nPrefix}.outputVars.usage`], { ns: 'workflow' })}
            />
          </>
        </OutputVars>
      </div>
    </div>
  )
}

export default React.memo(Panel)
