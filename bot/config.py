from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import SecretStr
import base64

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

_yookassa_headers = None
def get_yookassa_headers():
    """Build YooKassa API auth headers. Cached after first call."""
    global _yookassa_headers
    if _yookassa_headers is None:
        auth_str = f"{config.YOOKASSA_SHOP_ID}:{config.YOOKASSA_SECRET_KEY.get_secret_value()}"
        auth_bytes = auth_str.encode('ascii')
        base64_auth = base64.b64encode(auth_bytes).decode('ascii')
        _yookassa_headers = {
            "Authorization": f"Basic {base64_auth}",
            "Content-Type": "application/json"
        }
    return _yookassa_headers
