import httpx
import logging
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from config import config

class MarzbanAPI:
    def __init__(self):
        self.base_url = config.MARZBAN_URL
        if not self.base_url.startswith(("http://", "https://")):
            self.base_url = f"http://{self.base_url}"
        
        self.username = config.MARZBAN_ADMIN_USERNAME
        self.password = config.MARZBAN_ADMIN_PASSWORD.get_secret_value()
        self.token: Optional[str] = None
        self.token_expiry: float = 0
        self._client: Optional[httpx.AsyncClient] = None

    async def get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=20.0, 
                verify=False,
                limits=httpx.Limits(max_connections=10, max_keepalive_connections=5)
            )
        return self._client

    async def _get_token(self) -> str:
        """Получение JWT-токена администратора."""
        if self.token and time.time() < self.token_expiry:
            return self.token

        url = f"{self.base_url}/api/admin/token"
        data = {
            "username": self.username,
            "password": self.password
        }
        
        client = await self.get_client()
        try:
            response = await client.post(url, data=data)
            response.raise_for_status()
            token_data = response.json()
            self.token = token_data["access_token"]
            self.token_expiry = time.time() + 3600  # 1 час
            logging.info("Successfully obtained Marzban admin token")
            return self.token
        except Exception as e:
            logging.error(f"Failed to get Marzban token: {e}")
            raise

    async def _get_headers(self) -> Dict[str, str]:
        token = await self._get_token()
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    async def create_user(self, username: str, data_limit_gb: int, expire_days: int) -> Dict[str, Any]:
        url = f"{self.base_url}/api/user"
        headers = await self._get_headers()
        data_limit_bytes = data_limit_gb * 1024 * 1024 * 1024
        from datetime import timezone
        expire_timestamp = int((datetime.now(timezone.utc) + timedelta(days=expire_days)).timestamp())
        
        payload = {
            "username": username,
            "data_limit": data_limit_bytes,
            "expire": expire_timestamp,
            "proxies": {"vless": {}},
            "inbounds": {}
        }
        
        client = await self.get_client()
        try:
            response = await client.post(url, json=payload, headers=headers)
            if response.status_code >= 400:
                logging.error(f"Marzban API Error {response.status_code}: {response.text}")
            response.raise_for_status()
            logging.info(f"User {username} created successfully in Marzban")
            return response.json()
        except Exception as e:
            logging.error(f"Error creating user {username} in Marzban: {e}")
            raise

    async def get_user_info(self, username: str) -> Dict[str, Any]:
        url = f"{self.base_url}/api/user/{username}"
        headers = await self._get_headers()
        
        client = await self.get_client()
        try:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logging.error(f"Error getting info for user {username}: {e}")
            raise

    async def reset_user_stats(self, username: str) -> bool:
        url = f"{self.base_url}/api/user/{username}/reset"
        headers = await self._get_headers()
        
        client = await self.get_client()
        try:
            response = await client.post(url, headers=headers)
            success = response.status_code == 200
            if success:
                logging.info(f"Stats reset for user {username}")
            return success
        except Exception as e:
            logging.error(f"Error resetting stats for user {username}: {e}")
            return False

    async def update_user_expiry(self, username: str, extra_days: int) -> Dict[str, Any]:
        user = await self.get_user_info(username)
        current_expire = user.get("expire")
        now_ts = int(time.time())
        if not current_expire or current_expire < now_ts:
            new_expire = now_ts + (extra_days * 86400)
        else:
            new_expire = current_expire + (extra_days * 86400)
            
        url = f"{self.base_url}/api/user/{username}"
        headers = await self._get_headers()
        payload = {"expire": new_expire}
        
        client = await self.get_client()
        try:
            response = await client.put(url, json=payload, headers=headers)
            response.raise_for_status()
            logging.info(f"Subscription extended for {username} by {extra_days} days")
            return response.json()
        except Exception as e:
            logging.error(f"Error extending subscription for {username}: {e}")
            raise

# Экземпляр API для использования в других модулях
marzban = MarzbanAPI()
