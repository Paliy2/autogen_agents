import autogen
import fastapi
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import socketio
import uvicorn
import os
from typing import Optional, TypeAlias, Any

from dotenv import load_dotenv, find_dotenv

from foundation.chat_session import ChatSession

load_dotenv(find_dotenv(".env"))

from settings import settings
from logger_config import base_logger, SIOAdapter

llm_config_params: dict[str, Any] = {
    "config_list": autogen.config_list_from_json(
        env_or_file="OAI_CONFIG_LIST",
        filter_dict=settings.llm_filter_dict
    ),
    "cache_seed": settings.llm_cache_seed,
}

app = fastapi.FastAPI()
sio = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins="*",
    logger=base_logger.getChild("socketio"),
    engineio_logger=base_logger.getChild("engineio")
)
socket_app = socketio.ASGIApp(sio, app)

os.makedirs("templates", exist_ok=True)
app.mount("/static", StaticFiles(directory="templates"), name="static")

ChatSessionObject: TypeAlias = 'ChatSession'
ActiveSessionsDict: TypeAlias = dict[str, ChatSessionObject]
active_sessions: ActiveSessionsDict = {}


@app.get("/", response_class=HTMLResponse)
async def get_index():
    with open("templates/index.html", "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


@sio.event
async def connect(sid: str, environ: dict, auth: Optional[dict] = None):
    session_logger = SIOAdapter(base_logger.getChild("SIOConnect"), {'sid': sid})
    session_logger.info(f"Client connected. Environ: {str(environ)[:200]}")
    if sid in active_sessions:
        session_logger.warning("Existing session found for SID on new connect. Cleaning up old one.")
        old_session = active_sessions.pop(sid)
        await old_session.cleanup_on_disconnect()
    active_sessions[sid] = ChatSession(
        sid=sid, sio_instance=sio, llm_conf=llm_config_params, app_settings=settings
    )
    await sio.emit('assistant_message', {
        'sender': 'System', 'content': 'Welcome! Enter a topic to start.'
    }, room=sid)


@sio.event
async def disconnect(sid: str):
    session_logger = SIOAdapter(base_logger.getChild("SIODisconnect"), {'sid': sid})
    session_logger.info("Client disconnected.")
    session = active_sessions.pop(sid, None)
    if session:
        await session.cleanup_on_disconnect()
    else:
        session_logger.warning("No active session found to cleanup on disconnect.")
    session_logger.info(f"Active sessions remaining: {len(active_sessions)}")


@sio.on('start_chat')
async def handle_start_chat(sid: str, data: dict):
    session_logger = SIOAdapter(base_logger.getChild("SIOStartChat"), {'sid': sid})
    session = active_sessions.get(sid)
    if not session:
        session_logger.error("No session found for SID.")
        await sio.emit('assistant_message', {
            'sender': 'System', 'content': 'Error: Session not found. Please refresh and reconnect.'
        }, room=sid)
        return
    topic = data.get("topic", settings.default_poem_topic)
    if not isinstance(topic, str) or not topic.strip():
        topic = settings.default_poem_topic
        session_logger.warning(f"Invalid or empty topic received, using default: {topic}")
    await session.start_new_chat(topic)


@sio.on('user_response')
async def handle_user_response(sid: str, data: dict):
    session_logger = SIOAdapter(base_logger.getChild("SIOUserResponse"), {'sid': sid})
    session = active_sessions.get(sid)
    if not session:
        session_logger.error("No session found for SID.")
        await sio.emit('assistant_message', {
            'sender': 'System', 'content': 'Error: No active chat session. Please start a new chat.'
        }, room=sid)
        return
    message_text = data.get('message')
    if isinstance(message_text, str):
        await session.handle_user_response(message_text)
    else:
        session_logger.warning("Received non-string or missing message in user_response.")


if __name__ == "__main__":
    base_logger.info(f"Starting server on {settings.server_host}:{settings.server_port}")
    uvicorn.run(
        socket_app, host=settings.server_host, port=settings.server_port, log_level=settings.log_level.lower()
    )
