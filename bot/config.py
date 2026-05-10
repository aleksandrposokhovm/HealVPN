from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import SecretStr

class Settings(BaseSettings):
    BOT_TOKEN: SecretStr
    YOOKASSA_SHOP_ID: str
    YOOKASSA_SECRET_KEY: SecretStr
    
    # VPN Server settings (to be filled later)
    VPN_SERVER_IP: str = ""
    VPN_API_URL: str = ""
    
    # Supabase settings
    SUPABASE_URL: str
    SUPABASE_KEY: SecretStr
    
    # Marzban settings
    MARZBAN_URL: str
    MARZBAN_ADMIN_USERNAME: str
    MARZBAN_ADMIN_PASSWORD: SecretStr
    
    DB_NAME: str = "healvpn.db"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

config = Settings()

# Direct export for python-telegram-bot compatibility as requested by user
TELEGRAM_BOT_TOKEN = config.BOT_TOKEN.get_secret_value()
