import asyncio
from typing import Any, Optional

import socketio
from autogen import AssistantAgent, GroupChatManager

from foundation.broadcast_chat import BroadcastGroupChat
from foundation.proxy_agent import WebSocketUserProxyAgent
from logger_config import base_logger, SIOAdapter
from settings import AppSettings


class ChatSession:
    def __init__(self, sid: str,
                 sio_instance: socketio.AsyncServer,
                 llm_conf: dict[str, Any],
                 app_settings: AppSettings):
        self.sid = sid
        self.sio_server = sio_instance
        self.llm_config = llm_conf
        self.settings = app_settings
        self.logger = SIOAdapter(base_logger.getChild("ChatSession"), {'sid': self.sid})
        self.user_proxy: Optional[WebSocketUserProxyAgent] = None
        self.poet: Optional[AssistantAgent] = None
        self.groupchat: Optional[BroadcastGroupChat] = None
        self.manager: Optional[GroupChatManager] = None
        self.chat_task: Optional[asyncio.Task[None]] = None
        self.is_running = False
        self.logger.info("ChatSession initialized.")

    def _initialize_agents(self):
        self.logger.info("Initializing agents for session.")
        self.user_proxy = WebSocketUserProxyAgent(
            name="UserProxy",
            human_input_mode="ALWAYS",
            sio_server=self.sio_server,
            client_sid=self.sid,
            human_input_timeout=self.settings.human_input_timeout,
            logger_adapter=SIOAdapter(base_logger.getChild("UserProxy"), {'sid': self.sid}),
            code_execution_config=False,
            is_termination_msg=lambda x: isinstance(x, dict) and x.get("content", "").strip().lower() == "exit",
            default_auto_reply=""
        )
        self.poet = AssistantAgent(
            name="Poet",
            system_message=(
                "You are a creative poet. Your primary goal is to write a poem based on the user's topic. "
                "After presenting the first draft of the poem, or any subsequent revision, ALWAYS ask the user for feedback by saying something like 'What do you think of this draft?' or 'How would you like to revise it?'. "
                "Carefully consider any feedback provided by the user and revise the poem accordingly. "
                "Only use the word 'TERMINATE' (and nothing else in that message) if the user explicitly indicates they are satisfied with the poem (e.g., they say 'it's perfect', 'looks good', 'no more changes') or if they ask to end the session. "
                "Do not use 'TERMINATE' after just one draft unless the user explicitly approves it."
            ),
            llm_config=self.llm_config,
        )
        self.groupchat = BroadcastGroupChat(
            agents=[self.user_proxy, self.poet],
            messages=[],
            max_round=self.settings.max_chat_rounds,
            sio_server=self.sio_server,
            client_sid=self.sid,
            logger_adapter=SIOAdapter(base_logger.getChild("GroupChat"), {'sid': self.sid}),
            speaker_selection_method="round_robin"
        )
        self.manager = GroupChatManager(
            groupchat=self.groupchat,
            llm_config=self.llm_config,
            is_termination_msg=lambda x: isinstance(x, dict) and x.get("content", "").strip().lower() == "terminate"
        )
        self.logger.info("Agents initialized successfully.")

    async def start_new_chat(self, topic: str):
        if self.is_running:
            self.logger.warning("Attempted to start a new chat while one is already running.")
            await self.sio_server.emit('assistant_message', {
                'sender': 'System',
                'content': 'A chat is already in progress. Please wait or refresh.'
            }, room=self.sid)
            return

        self.logger.info(f"Starting new chat with topic: '{topic}'")
        await self.sio_server.emit('assistant_message', {
            'sender': 'System',
            'content': f"Starting poem about: '{topic}'..."
        }, room=self.sid)

        self._initialize_agents()
        self.is_running = True
        initial_message = f"Write a poem about: {topic}"

        async def _chat_interaction_runner():
            final_message = "Chat ended unexpectedly."
            try:
                if not self.user_proxy or not self.manager:
                    self.logger.error("UserProxy or Manager not initialized before starting chat.")
                    raise RuntimeError("Critical components not initialized.")
                await self.user_proxy.a_initiate_chat(
                    recipient=self.manager, message=initial_message,
                )
                final_message = "Chat ended. You can start a new one by entering a topic."
                self.logger.info("Chat interaction completed.")
            except asyncio.CancelledError:
                final_message = "Chat cancelled by client disconnection or server shutdown."
                self.logger.info("Chat task was cancelled.")
            except Exception as e:
                self.logger.error(f"Unexpected error during chat: {e}", exc_info=True)
                final_message = f"An unexpected server error occurred. Chat ended. Details: {str(e)[:100]}"
            finally:
                self.is_running = False
                current_task = asyncio.current_task()
                if not (current_task and current_task.cancelled()):
                    await self.sio_server.emit('assistant_message', {
                        'sender': 'System', 'content': final_message
                    }, room=self.sid)

                if self.chat_task is asyncio.current_task():
                    self.chat_task = None
                self.logger.info("Chat interaction runner finished.")

        self.chat_task = asyncio.create_task(_chat_interaction_runner())

    async def handle_user_response(self, message: str):
        if not self.is_running or not self.user_proxy:
            self.logger.warning("Received user response, but no active chat or user_proxy.")
            await self.sio_server.emit('assistant_message', {
                'sender': 'System',
                'content': 'Error: No active chat session to respond to. Please start a new chat.'
            }, room=self.sid)
            return
        if message:
            self.user_proxy.set_human_input_response(message)
        else:
            self.logger.info("Received empty user response.")

    async def cleanup_on_disconnect(self):
        self.logger.info("Cleaning up session on disconnect.")
        if self.chat_task and not self.chat_task.done():
            self.logger.info("Cancelling active chat task.")
            self.chat_task.cancel()
            try:
                await self.chat_task
            except asyncio.CancelledError:
                self.logger.info("Chat task successfully cancelled.")
            except Exception as e:
                self.logger.error(f"Error during chat task cancellation: {e}", exc_info=True)
        if self.user_proxy and self.user_proxy._input_future and not self.user_proxy._input_future.done():
            self.logger.info("Resolving pending input future for UserProxy due to disconnect.")
            self.user_proxy._input_future.set_exception(
                asyncio.CancelledError("Client disconnected while awaiting input"))
        self.logger.info("Session cleanup complete.")
