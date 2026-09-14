# Channel adapters package (P5MSG-03)
from app.adapters.channel_adapter import (
    ChannelAdapter,
    ChannelAdapterRegistry,
    ReceivedMessage,
    SendResult,
    UnsupportedChannelError,
)
from app.adapters.bitbrowser_channel_adapter import BitBrowserChannelAdapter

__all__ = [
    "ChannelAdapter",
    "ChannelAdapterRegistry",
    "ReceivedMessage",
    "SendResult",
    "UnsupportedChannelError",
    "BitBrowserChannelAdapter",
]
