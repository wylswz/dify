from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.tools.entities.tool_entities import ToolProviderType
from graphon.entities.base_node_data import BaseNodeData
from graphon.enums import NodeType
from graphon.nodes.llm.entities import ModelConfig

INTENT_EXECUTOR_NODE_TYPE: NodeType = "intent-executor"


class IntentExecutorToolConfig(BaseModel):
    """Tool selection payload, mirroring the frontend ``ToolValue`` shape used by
    the Agent v1 ``array[tools]`` parameter."""

    model_config = ConfigDict(extra="allow")

    provider_name: str
    type: ToolProviderType = ToolProviderType.BUILT_IN
    tool_name: str
    plugin_unique_identifier: str | None = None
    credential_id: str | None = None
    enabled: bool = True
    settings: dict[str, Any] = Field(default_factory=dict)
    parameters: dict[str, Any] = Field(default_factory=dict)
    extra: dict[str, Any] = Field(default_factory=dict)


class IntentExecutorNodeData(BaseNodeData):
    type: NodeType = INTENT_EXECUTOR_NODE_TYPE
    model: ModelConfig
    instruction: str = ""
    intents: list[str] = Field(default_factory=list)
    tools: list[IntentExecutorToolConfig] = Field(default_factory=list)
    max_parallelism: int = Field(default=4, ge=1, le=16)
