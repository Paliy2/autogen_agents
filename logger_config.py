import logging
from typing import MutableMapping, Any
from settings import settings


class SIOAdapter(logging.LoggerAdapter):
    def process(self, msg: str, kwargs: MutableMapping[str, Any]) -> tuple[str, MutableMapping[str, Any]]:
        sid = kwargs.pop('sid', self.extra.get('sid', 'N/A'))
        return f'[SID:{sid}] {msg}', kwargs


def setup_logging():
    logging.basicConfig(
        level=settings.log_level.upper(),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    logging.getLogger("socketio").setLevel(logging.WARNING)
    logging.getLogger("engineio").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


setup_logging()
base_logger = logging.getLogger("autogen_fastapi_app")
