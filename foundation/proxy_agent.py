import asyncio
from typing import Any, Optional
from logger_config import SIOAdapter

import socketio
from autogen import UserProxyAgent


class WebSocketUserProxyAgent(UserProxyAgent):
    def __init__(self, name: str,
                 sio_server: socketio.AsyncServer,
                 client_sid: str,
                 human_input_timeout: float,
                 logger_adapter: SIOAdapter,
                 *args: Any, **kwargs: Any):
        super().__init__(name, *args, **kwargs)
        self.sio = sio_server
        self.client_sid = client_sid
        self.human_input_timeout = human_input_timeout
        self.logger = logger_adapter
        self._input_future: Optional[asyncio.Future[str]] = None

    async def a_get_human_input(self, prompt: str) -> str:
        self.logger.info(f"Prompting user: {prompt[:200]}...")
        user_prompt_message = prompt
        if "Provide feedback to the writer." in prompt or "What's next?" in prompt or "Waiting for your response..." in prompt:
             user_prompt_message = "The Poet has responded. What would you like to do next?\n(e.g., 'Revise the first line', 'Change the theme to X', 'Looks good!', or 'exit')"
        else:
            user_prompt_message = prompt + "\n(Type your response and press Send, or type 'exit' to end the current interaction.)"


        await self.sio.emit('assistant_message', {
            'sender': self.name,
            'content': user_prompt_message
        }, room=self.client_sid)

        self._input_future = asyncio.get_event_loop().create_future()

        try:
            return await asyncio.wait_for(self._input_future, timeout=self.human_input_timeout)
        except asyncio.TimeoutError:
            self.logger.warning("Timeout waiting for user input.")
            await self.sio.emit('assistant_message', {
                'sender': 'System',
                'content': 'Timeout waiting for user input. Interaction will proceed as if you typed "exit".'
            }, room=self.client_sid)
            return "exit"
        except asyncio.CancelledError:
            self.logger.info("Input request cancelled for user.")
            return "exit"
        finally:
            self._input_future = None

    def set_human_input_response(self, message: str):
        if self._input_future and not self._input_future.done():
            self.logger.info(f"Received human input: {message[:100]}")
            self._input_future.set_result(message)
        else:
            self.logger.warning(f"Received input '{message[:100]}' but no future was waiting or future already done.")
