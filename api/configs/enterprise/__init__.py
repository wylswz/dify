from pydantic import Field
from pydantic_settings import BaseSettings


class EnterpriseFeatureConfig(BaseSettings):
    """
    Configuration for enterprise-level features.
    **Before using, please contact business@dify.ai by email to inquire about licensing matters.**
    """

    ENTERPRISE_ENABLED: bool = Field(
        description="Enable or disable enterprise-level features."
        "Before using, please contact business@dify.ai by email to inquire about licensing matters.",
        default=False,
    )

    CAN_REPLACE_LOGO: bool = Field(
        description="Allow customization of the enterprise logo.",
        default=False,
    )

    ENTERPRISE_TRACE_ENABLED: bool = Field(
        description="Enable or disable enterprise tracing.",
        default=True,
    )

    # Enterprise OTLP tracing configuration
    # When ENTERPRISE_ENABLED=true, tracing is implicitly enabled for all apps
    ENTERPRISE_TRACE_ENDPOINT: str = Field(
        description="OTLP endpoint URL for enterprise tracing (e.g., http://localhost:14318/v1/traces)",
        default="http://localhost:14318/v1/traces",
    )

    ENTERPRISE_TRACE_SERVICE_NAME: str = Field(
        description="Service name for enterprise tracing",
        default="dify_app",
    )

    ENTERPRISE_TRACE_TOKEN: str | None = Field(
        description="Optional bearer token for OTLP endpoint authentication",
        default=None,
    )
