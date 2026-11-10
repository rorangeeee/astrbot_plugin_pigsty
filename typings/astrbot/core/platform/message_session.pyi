from .message_type import MessageType

class MessageSession:
    platform_name: str
    platform_id: str
    message_type: MessageType
    session_id: str
    def __init__(
        self, platform_name: str, message_type: MessageType, session_id: str
    ) -> None: ...
    @staticmethod
    def from_str(session_str: str) -> MessageSession: ...
