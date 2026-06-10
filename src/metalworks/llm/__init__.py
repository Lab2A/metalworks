"""LLM access layer: a small, versioned protocol + adapters over official SDKs.

Core carries zero provider dependencies. Adapters live behind extras:

    pip install "metalworks[anthropic]"   → metalworks.llm.adapters.anthropic
    pip install "metalworks[openai]"      → metalworks.llm.adapters.openai
    pip install "metalworks[google]"      → metalworks.llm.adapters.google

`FakeChatModel` ships in core so users can test their own integrations the
same way metalworks tests itself.
"""

from metalworks.llm.fake import FakeChatModel
from metalworks.llm.protocol import (
    PROTOCOL_VERSION,
    ChatCapabilities,
    ChatModel,
    GroundedChatModel,
    GroundedResult,
    GroundingChunk,
    GroundingSupport,
    TextResult,
    Usage,
)

__all__ = [
    "PROTOCOL_VERSION",
    "ChatCapabilities",
    "ChatModel",
    "FakeChatModel",
    "GroundedChatModel",
    "GroundedResult",
    "GroundingChunk",
    "GroundingSupport",
    "TextResult",
    "Usage",
]
