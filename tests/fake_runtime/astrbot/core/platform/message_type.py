"""Host message types used when serializing notification sessions."""

from enum import Enum


class MessageType(Enum):
    """Mirror the host's exact message-type wire values."""

    GROUP_MESSAGE = "GroupMessage"
    FRIEND_MESSAGE = "FriendMessage"
    OTHER_MESSAGE = "OtherMessage"
