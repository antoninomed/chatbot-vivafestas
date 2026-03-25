from alembic.environment import Optional
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    
    
    SCHOOL_NAME: str = "Kit Festa"

    WEBHOOK_VERIFY_TOKEN: str

    META_ACCESS_TOKEN: str
    META_PHONE_NUMBER_ID: str
    META_APP_SECRET: str
    META_GRAPH_VERSION: str = "v20.0"

    DATABASE_URL: str

    # ⬇️ ADICIONE ISSO
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_MODEL: str = "gpt-4o-mini"

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()