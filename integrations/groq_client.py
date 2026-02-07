"""
Groq API Client - LLM integration with retry/backoff logic.
"""
import os
import json
import logging
from typing import Optional, Type, TypeVar
from pydantic import BaseModel
import requests
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type
)

logger = logging.getLogger(__name__)

T = TypeVar('T', bound=BaseModel)


class GroqRateLimitError(Exception):
    """Raised when Groq API returns 429 Too Many Requests."""
    pass


class GroqAPIError(Exception):
    """General Groq API error."""
    pass


class GroqClient:
    """Client for Groq API with retry logic and structured outputs."""
    
    BASE_URL = "https://api.groq.com/openai/v1/chat/completions"
    
    # Available models on Groq
    MODELS = {
        # Fast models for agent 1 and 2
        "qwen-qwq-32b": "qwen-qwq-32b",
        "llama-3.3-70b": "llama-3.3-70b-versatile",
        "llama-3.1-8b": "llama-3.1-8b-instant",
        "gemma2-9b": "gemma2-9b-it",
        "mixtral-8x7b": "mixtral-8x7b-32768",
        # Recommended for Agent 3 (final report)
        "llama-3.3-70b-specdec": "llama-3.3-70b-specdec",
        "deepseek-r1-distill-llama-70b": "deepseek-r1-distill-llama-70b",
    }
    
    # Default model assignments
    DEFAULT_FAST_MODEL = "qwen-qwq-32b"
    DEFAULT_POWERFUL_MODEL = "llama-3.3-70b"
    
    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize Groq client.
        
        Args:
            api_key: Groq API key
        """
        self.api_key = api_key or os.getenv("GROQ_API_KEY")
        if not self.api_key:
            raise ValueError("GROQ_API_KEY is required")
        
        self.session = requests.Session()
        self.session.headers["Authorization"] = f"Bearer {self.api_key}"
        self.session.headers["Content-Type"] = "application/json"
    
    @retry(
        retry=retry_if_exception_type(GroqRateLimitError),
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=2, min=4, max=60)
    )
    def _make_request(self, payload: dict) -> dict:
        """Make API request with retry logic for rate limits."""
        try:
            resp = self.session.post(self.BASE_URL, json=payload, timeout=120)
            
            if resp.status_code == 429:
                logger.warning("Rate limited by Groq API, retrying...")
                raise GroqRateLimitError("Rate limited")
            
            if resp.status_code != 200:
                error_msg = resp.text
                logger.error(f"Groq API error: {error_msg}")
                raise GroqAPIError(f"API error {resp.status_code}: {error_msg}")
            
            return resp.json()
        
        except requests.RequestException as e:
            logger.error(f"Request failed: {e}")
            raise GroqAPIError(f"Request failed: {e}")
    
    def complete(
        self,
        prompt: str,
        model: Optional[str] = None,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        json_mode: bool = False
    ) -> str:
        """
        Generate a completion from Groq.
        
        Args:
            prompt: User prompt
            model: Model to use (defaults to fast model)
            system_prompt: System prompt for context
            temperature: Sampling temperature (0.0 - 1.0)
            max_tokens: Maximum tokens in response
            json_mode: If True, request JSON output format
            
        Returns:
            Generated text response
        """
        model_id = self.MODELS.get(model, model) or self.MODELS[self.DEFAULT_FAST_MODEL]
        
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        
        payload = {
            "model": model_id,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        
        response = self._make_request(payload)
        
        content = response["choices"][0]["message"]["content"]
        return content
    
    def complete_structured(
        self,
        prompt: str,
        response_model: Type[T],
        model: Optional[str] = None,
        system_prompt: Optional[str] = None,
        temperature: float = 0.3
    ) -> T:
        """
        Generate a structured response validated by Pydantic.
        
        Args:
            prompt: User prompt
            response_model: Pydantic model class for response validation
            model: Model to use
            system_prompt: System prompt for context
            temperature: Sampling temperature
            
        Returns:
            Validated Pydantic model instance
        """
        # Build a JSON-specific system prompt
        schema_json = json.dumps(response_model.model_json_schema(), indent=2)
        
        json_system = f"""You are a helpful assistant that ONLY outputs valid JSON.
Your response must be a valid JSON object matching this schema:

{schema_json}

Do not include any text before or after the JSON. Only output the JSON object."""
        
        if system_prompt:
            json_system = f"{system_prompt}\n\n{json_system}"
        
        # Request completion in JSON mode
        response = self.complete(
            prompt=prompt,
            model=model,
            system_prompt=json_system,
            temperature=temperature,
            max_tokens=8192,
            json_mode=True
        )
        
        # Parse and validate response
        try:
            # Clean response - sometimes LLMs add markdown code blocks
            clean_response = response.strip()
            if clean_response.startswith("```"):
                # Remove code block markers
                lines = clean_response.split("\n")
                clean_response = "\n".join(lines[1:-1])
            
            data = json.loads(clean_response)
            return response_model.model_validate(data)
        
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response: {e}")
            logger.error(f"Response was: {response[:500]}...")
            raise GroqAPIError(f"Invalid JSON response: {e}")
        
        except Exception as e:
            logger.error(f"Failed to validate response: {e}")
            raise GroqAPIError(f"Validation failed: {e}")
    
    def get_available_models(self) -> list:
        """Return list of available model names."""
        return list(self.MODELS.keys())
