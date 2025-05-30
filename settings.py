from pydantic_settings import BaseSettings
from typing import List, Dict, Optional
from dotenv import load_dotenv, find_dotenv


class AppSettings(BaseSettings):
    llm_filter_dict: Dict[str, List[str]] = {"model": ["gpt-3.5-turbo", "gpt-4"]}
    llm_cache_seed: Optional[int] = 42

    human_input_timeout: float = 300.0
    max_chat_rounds: int = 15
    default_poem_topic: str = "a beautiful sunset"

    server_host: str = "0.0.0.0"
    server_port: int = 8000

    log_level: str = "INFO"

    class Config:
        env_file = ".env"
        env_file_encoding = 'utf-8'
        extra = 'ignore'


load_dotenv(find_dotenv())
settings = AppSettings()
