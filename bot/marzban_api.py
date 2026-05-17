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

    def extract_token(self, url: str) -> Optional[str]:
        """Safely extract token from subscription URL or VLESS link."""
        if not url:
            return None
        if "/sub/" in url:
            try:
                # Extract part after /sub/
                part = url.split('/sub/')[1]
                # Remove query params, fragments, and trailing slashes
                token = part.split('?')[0].split('#')[0].split('/')[0]
                return token if token else None
            except Exception:
                return None
        return None

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
        forced_token: Optional[str] = None, proxies: Optional[Dict] = None,
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
            "proxies": proxies or {"vless": {}},
            "inbounds": {},
            "data_limit": data_limit,
            "expire": expire,
            "data_limit_reset_strategy": "no_reset",
            "status": "active",
        }
        
        if forced_token:
            payload["token"] = forced_token
            payload["subscription_url_token"] = forced_token

        try:
            response = await self.get_client().post(
                f"{self.base_url}/api/user", json=payload, headers=headers
            )

            if response.status_code == 401 and not _retry:
                self.token = None # Reset token on unauthorized
                return await self.create_user(username, data_limit, expire, forced_token, proxies, _retry=True)
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
            elif response.status_code == 404:
                return None
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logging.error(f"Error getting user from Marzban: {e}")
            return None

    async def update_user(self, username: str, payload: Dict[str, Any], _retry: bool = False) -> bool:
        """Generic PUT /api/user/{username} update."""
        token = await self.get_token()
        if not token:
            return False

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        try:
            logging.info(f"Updating user {username} in Marzban...")
            response = await self.get_client().put(
                f"{self.base_url}/api/user/{username}",
                json=payload,
                headers=headers,
            )

            if response.status_code == 401 and not _retry:
                self.token = None
                return await self.update_user(username, payload, _retry=True)

            if response.status_code != 200:
                logging.error(f"Failed to update user {username}. Status: {response.status_code}, Body: {response.text}")
                return False

            return True
        except Exception as e:
            logging.error(f"Error in update_user for {username}: {e}")
            return False

    async def delete_user(self, username: str, _retry: bool = False) -> bool:
        """DELETE /api/user/{username}."""
        token = await self.get_token()
        if not token:
            return False

        headers = {"Authorization": f"Bearer {token}"}

        try:
            logging.info(f"Deleting user {username} from Marzban...")
            response = await self.get_client().delete(
                f"{self.base_url}/api/user/{username}",
                headers=headers,
            )

            if response.status_code == 401 and not _retry:
                self.token = None
                return await self.delete_user(username, _retry=True)

            if response.status_code not in [200, 204]:
                logging.error(f"Failed to delete user {username}. Status: {response.status_code}")
                return False

            return True
        except Exception as e:
            logging.error(f"Error in delete_user for {username}: {e}")
            return False

    async def sync_user_subscription(self, username: str, expire_ts: int, forced_token: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Unified method to ensure user exists and has updated expiration.
        Strictly preserves existing token/link.
        Returns the full user object from Marzban after sync.
        """
        # 1. Fetch current state
        current_user = await self.get_user(username)
        
        if not current_user:
            # Create new user
            logging.info(f"User {username} not found in Marzban, creating new...")
            # Use default proxies if none provided, or better: try to keep it empty if Marzban handles it
            user_data = await self.create_user(username, expire=expire_ts, forced_token=forced_token)
            return user_data

        # 2. User exists, prepare update to preserve everything except expiration and status
        # We MUST include the token to prevent Marzban from regenerating it
        token_to_use = forced_token
        if not token_to_use:
            token_to_use = current_user.get("token")
        
        # Extra extraction from subscription_url or links if 'token' field is missing
        if not token_to_use:
            possible_urls = []
            if current_user.get("subscription_url"):
                possible_urls.append(current_user.get("subscription_url"))
            if current_user.get("links"):
                possible_urls.extend(current_user.get("links"))
            
            for url in possible_urls:
                token_to_use = self.extract_token(url)
                if token_to_use:
                    logging.info(f"Extracted token {token_to_use[:12]}... from Marzban response for {username}")
                    break

        payload = {
            "proxies": current_user.get("proxies") or {"vless": {}},
            "inbounds": current_user.get("inbounds") or {},
            "expire": expire_ts,
            "data_limit": current_user.get("data_limit", 0),
            "data_limit_reset_strategy": current_user.get("data_limit_reset_strategy", "no_reset"),
            "status": "active",
            "note": current_user.get("note") or "",
            "on_hold_timeout": current_user.get("on_hold_timeout"),
            "on_hold_expire_duration": current_user.get("on_hold_expire_duration", 0),
            "token": token_to_use,
            "subscription_url_token": token_to_use # Some versions use this field
        }

        # Add excluded_inbounds if it exists
        if "excluded_inbounds" in current_user:
            payload["excluded_inbounds"] = current_user["excluded_inbounds"]

        # Remove None values
        payload = {k: v for k, v in payload.items() if v is not None}
        
        if token_to_use:
            logging.info(f"Syncing user {username}: explicitly preserving token {token_to_use[:12]}...")
        else:
            logging.warning(f"Syncing user {username}: NO TOKEN FOUND to preserve! Marzban might regenerate it.")

        success = await self.update_user(username, payload)
        
        if success:
            # Return fresh data
            res = await self.get_user(username)
            if res and token_to_use:
                res["token"] = token_to_use # Ensure token is present in return
            return res
        
        return None

    async def update_user_expire(self, username: str, expire_ts: int, forced_token: Optional[str] = None) -> bool:
        """Legacy wrapper for backward compatibility."""
        res = await self.sync_user_subscription(username, expire_ts, forced_token)
        return res is not None

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
