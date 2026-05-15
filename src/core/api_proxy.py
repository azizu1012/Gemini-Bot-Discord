"""
API Proxy Module - Route Gemini API calls through external relay server

Use cases:
1. VPS bị Google chặn IP → route qua Colab/Cloudflare Worker
2. Load balancing qua nhiều relay servers
3. Bypass rate limits bằng cách distribute requests

Relay Server có thể là:
- Google Colab notebook running Flask/FastAPI
- Cloudflare Worker (free tier)
- Self-hosted server với clean IP

Relay Protocol (JSON):
Request:
{
    "action": "generate",
    "api_key": "xxx",
    "model": "<provider_model_id>",
    "contents": [...],
    "config": {...},
    "secret": "relay_auth_secret"
}

Response:
{
    "success": true,
    "text": "response text",
    "error": null
}
"""
import aiohttp
import asyncio
import json
from typing import Optional, Dict, Any, List
from dataclasses import dataclass


@dataclass
class RelayResponse:
    """Response from relay server"""
    success: bool
    text: str = ""
    error: str = ""
    model_used: str = ""


class APIProxy:
    """
    Proxy để route Gemini API calls qua external server.
    Hỗ trợ cả direct call và relay call.
    """
    
    def __init__(self, relay_url: str = "", relay_secret: str = "", timeout: int = 60):
        self.relay_url = relay_url
        self.relay_secret = relay_secret
        self.timeout = timeout
        self._session: Optional[aiohttp.ClientSession] = None
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session"""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout)
            )
        return self._session
    
    async def close(self):
        """Close session"""
        if self._session and not self._session.closed:
            await self._session.close()
    
    async def call_via_relay(
        self,
        api_key: str,
        model: str,
        contents: List[Any],
        generation_config: Dict[str, Any],
        system_instruction: str = "",
        safety_settings: List[Dict] = None
    ) -> RelayResponse:
        """
        Gọi Gemini API thông qua relay server.
        
        Args:
            api_key: Gemini API key
            model: Provider model id (from router/config)
            contents: List of content parts
            generation_config: Generation config dict
            system_instruction: System prompt
            safety_settings: Safety settings list
        
        Returns:
            RelayResponse with success/text/error
        """
        if not self.relay_url:
            return RelayResponse(success=False, error="Relay URL not configured")
        
        try:
            session = await self._get_session()
            
            # Prepare request payload
            payload = {
                "action": "generate",
                "api_key": api_key,
                "model": model,
                "contents": self._serialize_contents(contents),
                "config": generation_config,
                "system_instruction": system_instruction,
                "safety_settings": safety_settings or [],
                "secret": self.relay_secret
            }
            
            async with session.post(
                self.relay_url,
                json=payload,
                headers={"Content-Type": "application/json"}
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    return RelayResponse(
                        success=data.get("success", False),
                        text=data.get("text", ""),
                        error=data.get("error", ""),
                        model_used=data.get("model_used", model)
                    )
                else:
                    error_text = await response.text()
                    return RelayResponse(
                        success=False,
                        error=f"Relay HTTP {response.status}: {error_text[:200]}"
                    )
        
        except asyncio.TimeoutError:
            return RelayResponse(success=False, error="Relay timeout")
        except aiohttp.ClientError as e:
            return RelayResponse(success=False, error=f"Relay connection error: {str(e)}")
        except Exception as e:
            return RelayResponse(success=False, error=f"Relay error: {str(e)}")
    
    def _serialize_contents(self, contents: List[Any]) -> List[Dict]:
        """Serialize contents to JSON-safe format"""
        result = []
        for item in contents:
            if isinstance(item, dict):
                result.append(item)
            elif hasattr(item, '__dict__'):
                # Convert object to dict
                result.append(self._obj_to_dict(item))
            else:
                result.append({"text": str(item)})
        return result
    
    def _obj_to_dict(self, obj: Any) -> Any:
        """Convert object to JSON-safe recursively"""
        if isinstance(obj, dict):
            return {k: self._obj_to_dict(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._obj_to_dict(item) for item in obj]
        elif hasattr(obj, '__dict__'):
            return {k: self._obj_to_dict(v) for k, v in obj.__dict__.items() 
                    if not k.startswith('_')}
        else:
            return obj
    
    async def health_check(self) -> bool:
        """Check if relay server is reachable"""
        if not self.relay_url:
            return False
        
        try:
            session = await self._get_session()
            
            # Simple health check
            check_url = self.relay_url.rstrip('/') + '/health'
            async with session.get(check_url, timeout=aiohttp.ClientTimeout(total=5)) as response:
                return response.status == 200
        except:
            # Try pinging main URL
            try:
                async with session.post(
                    self.relay_url,
                    json={"action": "ping", "secret": self.relay_secret}
                ) as response:
                    return response.status == 200
            except:
                return False


# ============================================================================
# RELAY SERVER TEMPLATE (để deploy trên Colab/Worker)
# ============================================================================

RELAY_SERVER_TEMPLATE = '''
"""
Relay Server Template - Deploy trên Google Colab hoặc VPS clean IP

Cách dùng:
1. Copy code này vào Colab notebook
2. Chạy và lấy ngrok URL
3. Set GEMINI_RELAY_URL trong .env của bot

Dependencies: flask, google-genai, pyngrok
"""
from flask import Flask, request, jsonify
import os

# Uncomment nếu dùng Colab
# !pip install flask google-genai pyngrok
# from pyngrok import ngrok

app = Flask(__name__)
RELAY_SECRET = os.getenv("RELAY_SECRET", "your-secret-here")

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})

@app.route("/", methods=["POST"])
def relay():
    try:
        data = request.json
        
        # Verify secret
        if data.get("secret") != RELAY_SECRET:
            return jsonify({"success": False, "error": "Unauthorized"}), 401
        
        action = data.get("action")
        
        if action == "ping":
            return jsonify({"success": True, "text": "pong"})
        
        if action == "generate":
            from google import genai
            
            api_key = data.get("api_key")
            model = data.get("model")
            if not model:
                return jsonify({"success": False, "error": "Missing model"}), 400
            contents = data.get("contents", [])
            config = data.get("config", {})
            system_instruction = data.get("system_instruction", "")
            
            client = genai.Client(api_key=api_key)
            
            response = client.models.generate_content(
                model=model,
                contents=contents,
                config=config
            )
            
            text = ""
            if response.candidates:
                candidate = response.candidates[0]
                if candidate.content and candidate.content.parts:
                    text = candidate.content.parts[0].text
            
            return jsonify({
                "success": True,
                "text": text,
                "model_used": model
            })
        
        return jsonify({"success": False, "error": "Unknown action"})
    
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

if __name__ == "__main__":
    # Nếu dùng Colab, uncomment để expose qua ngrok
    # public_url = ngrok.connect(5000)
    # print(f"Relay URL: {public_url}")
    
    app.run(host="0.0.0.0", port=5000)
'''


def get_relay_server_code() -> str:
    """Get relay server template code"""
    return RELAY_SERVER_TEMPLATE
