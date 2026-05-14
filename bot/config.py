from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import SecretStr

class Settings(BaseSettings):
    BOT_TOKEN: SecretStr
    YOOKASSA_SHOP_ID: str
    YOOKASSA_SECRET_KEY: SecretStr
    
    # VPN Server settings
    VPN_SERVER_IP: str = ""
    VPN_API_URL: str = ""

    # Marzban credentials (supports both MARZBAN_USERNAME and MARZBAN_ADMIN_USERNAME in .env)
    MARZBAN_USERNAME: str = ""
    MARZBAN_PASSWORD: str = ""
    MARZBAN_ADMIN_USERNAME: str = ""
    MARZBAN_ADMIN_PASSWORD: str = ""

    # Database settings
    DATABASE_URL: str

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

config = Settings()

# Direct export for python-telegram-bot compatibility as requested by user
TELEGRAM_BOT_TOKEN = config.BOT_TOKEN.get_secret_value()
