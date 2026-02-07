"""
Base agent class for all agents.
"""
from abc import ABC, abstractmethod
from typing import Optional, Any
import logging

from integrations.groq_client import GroqClient

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    """Base class for all agents in the pipeline."""
    
    def __init__(
        self,
        groq_client: GroqClient,
        model: Optional[str] = None
    ):
        """
        Initialize agent.
        
        Args:
            groq_client: Groq API client
            model: Model to use for this agent
        """
        self.groq = groq_client
        self.model = model
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Agent name for logging."""
        pass
    
    @property
    @abstractmethod
    def role_prompt(self) -> str:
        """System prompt defining agent's role."""
        pass
    
    @abstractmethod
    def run(self, **kwargs) -> Any:
        """Execute agent's main task."""
        pass
    
    def log(self, message: str, level: str = "info"):
        """Log a message with agent prefix."""
        log_func = getattr(logger, level, logger.info)
        log_func(f"[{self.name}] {message}")
