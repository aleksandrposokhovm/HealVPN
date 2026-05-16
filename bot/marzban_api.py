import httpx
import logging
from typing import Optional, Dict, Any
from .config import config


class MarzbanAPI:
    """Async client for Marzban panel API."""

    def __init__(self):
        self.base_url = (config.MARZBAN_URL or config.VPN_API_URL).rstrip('/')
        # Support both naming conventions from .env
        self.username = config.MARZBAN_ADMIN_USERNAME or config.MARZBAN_USERNAME
        self.password = config.MARZBAN_ADMIN_PASSWORD or config.MARZBAN_PASSWORD
        self.token: Optional[str] = None
        self._client: Optional[httpx.AsyncClient] = None

    def get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(verify=False)
        return self._client

    async def get_token(self) -> str:
        """Authenticate with Marzban and cache the access token."""
        if self.token:
            return self.token

        if not self.base_url or not self.username or not self.password:
            logging.error("Marzban API credentials are not set in config.")
            return ""

        try:
            response = await self.get_client().post(
                f"{self.base_url}/api/admin/token",
                data={"username": self.username, "password": self.password},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            response.raise_for_status()
            data = response.json()
            self.token = data.get("access_token", "")
            logging.info("Successfully obtained Marzban token.")
            return self.token
        except Exception as e:
            logging.error(f"Error getting Marzban token: {e}")
            return ""

    async def create_user(
        self, username: str, data_limit: int = 0, expire: int = 0,
        _retry: bool = False
    ) -> Optional[Dict[str, Any]]:
        """
        Create a user in Marzban and return the full API response dict.
        If the user already exists (409), fetch and return their info instead.
        """
        token = await self.get_token()
        if not token:
            return None

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        payload = {
            "username": username,
            "proxies": {"vless": {}},
            "inbounds": {},
            "data_limit": data_limit,
            "expire": expire,
            "data_limit_reset_strategy": "no_reset",
            "status": "active",
        }

        try:
            response = await self.get_client().post(
                f"{self.base_url}/api/user", json=payload, headers=headers
            )

            if response.status_code == 401 and not _retry:
                self.token = None # Reset token on unauthorized
                return await self.create_user(username, data_limit, expire, _retry=True)
            elif response.status_code == 401:
                logging.error("Marzban auth failed after retry")
                return None

            if response.status_code == 409:
                logging.info(
                    f"User {username} already exists in Marzban, fetching info..."
                )
                return await self.get_user(username)

            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logging.error(f"Marzban HTTP error: {e.response.text}")
            return None
        except Exception as e:
            logging.error(f"Error creating user in Marzban: {e}")
            return None

    async def get_user(self, username: str, _retry: bool = False) -> Optional[Dict[str, Any]]:
        """Fetch existing user info from Marzban."""
        token = await self.get_token()
        if not token:
            return None

        headers = {"Authorization": f"Bearer {token}"}

        try:
            response = await self.get_client().get(
                f"{self.base_url}/api/user/{username}", headers=headers
            )
            if response.status_code == 401 and not _retry:
                self.token = None # Reset token on unauthorized
                return await self.get_user(username, _retry=True)
            elif response.status_code == 401:
                logging.error("Marzban auth failed after retry")
                return None
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logging.error(f"Error getting user from Marzban: {e}")
            return None

    async def update_user_expire(self, username: str, expire_ts: int, _retry: bool = False) -> bool:
        """
        Update the expiry timestamp for an existing Marzban user.
        Preserves existing user data (proxies, data_limit, etc.) to avoid resets.
        """
        token = await self.get_token()
        if not token:
            return False

        # 1. Fetch current user data to preserve it
        current_user = await self.get_user(username)
        if not current_user:
            logging.error(f"Cannot update user {username}: user not found in Marzban")
            return False

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        # 2. Prepare payload by keeping existing essential fields
        # We only want to update 'expire' and 'status' while preserving everything else
        payload = {
            "proxies": current_user.get("proxies"),
            "inbounds": current_user.get("inbounds"),
            "expire": expire_ts,
            "data_limit": current_user.get("data_limit"),
            "data_limit_reset_strategy": current_user.get("data_limit_reset_strategy"),
            "status": "active",
            "note": current_user.get("note"),
            "on_hold_timeout": current_user.get("on_hold_timeout"),
            "on_hold_expire_duration": current_user.get("on_hold_expire_duration"),
        }
        
        # If user has a token, we MUST preserve it to keep the subscription link the same
        token_to_preserve = current_user.get("token")
        if not token_to_preserve and current_user.get("subscription_url"):
            sub_url = current_user.get("subscription_url")
            if "/sub/" in sub_url:
                token_to_preserve = sub_url.split("/sub/")[-1]

        if token_to_preserve:
            payload["token"] = token_to_preserve

        # Remove None values to avoid overwriting with defaults if field is missing in response
        payload = {k: v for k, v in payload.items() if v is not None}

        try:
            response = await self.get_client().put(
                f"{self.base_url}/api/user/{username}",
                json=payload,
                headers=headers,
            )
            if response.status_code == 401 and not _retry:
                self.token = None # Reset token on unauthorized
                return await self.update_user_expire(username, expire_ts, _retry=True)
            elif response.status_code == 401:
                logging.error("Marzban auth failed after retry")
                return False
            response.raise_for_status()
            logging.info(f"Updated Marzban expire for user {username} to {expire_ts}")
            return True
        except Exception as e:
            logging.error(f"Error updating Marzban user expire for {username}: {e}")
            return False

    async def validate_subscription(self, sub_url: str) -> bool:
        """
        Health-check: GET the subscription URL to verify it returns valid content.
        """
        if not sub_url:
            return False

        try:
            response = await self.get_client().get(sub_url, timeout=10.0)
            return response.status_code == 200 and len(response.text) > 10
        except Exception as e:
            logging.error(f"Error validating subscription URL {sub_url}: {e}")
            return False


marzban_api = MarzbanAPI()
