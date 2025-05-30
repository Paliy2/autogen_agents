import asyncio
from typing import Any, Callable, Union, Optional

import socketio
from autogen import GroupChat, Agent
from logger_config import SIOAdapter


class BroadcastGroupChat(GroupChat):
    def __init__(self,
                 agents: list[Agent],
                 messages: list[dict[str, Any]],
                 max_round: int,
                 sio_server: socketio.AsyncServer,
                 client_sid: str,
                 logger_adapter: SIOAdapter,
                 speaker_selection_method: Union[
                     str, Callable[[Optional[Agent], "GroupChat"], Optional[Agent]]] = "auto"):
        super().__init__(
            agents=agents,
            messages=messages,
            max_round=max_round,
            speaker_selection_method=speaker_selection_method
        )
        self.sio = sio_server
        self.client_sid = client_sid
        self.logger = logger_adapter

    def append(self, message: dict[str, Any], speaker: Agent):
        super().append(message, speaker)
        content = message.get("content")
        if speaker.name == "UserProxy" and (not content or content == "No response. Proceeding."):
            self.logger.info(f"Skipping broadcast of empty/default UserProxy message.")
            return

        if content and isinstance(content, str):
            self.logger.info(f"Broadcasting message from {speaker.name}: {content[:100]}...")
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self.sio.emit('assistant_message', {
                    'sender': speaker.name,
                    'content': content
                }, room=self.client_sid))
            except RuntimeError:
                self.logger.error("No running event loop to emit WebSocket message.")
