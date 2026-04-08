from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    from ..config_loader import ConfigLoader

import logging

logger = logging.getLogger(__name__)


class BasePhase(ABC):
    PHASE_TAG = "BUILD"

    def __init__(
        self,
        config: Dict[str, Any],
        config_loader: Optional["ConfigLoader"] = None,
    ):
        self._config = config
        self._config_loader = config_loader
        self._context: Dict[str, Any] = {}
        self._verbose = config.get("verbose", False)

    @property
    @abstractmethod
    def name(self) -> str:
        pass

    def update_context(self, key: str, value: Any) -> None:
        self._context[key] = value

    def get_context(self, key: str, default: Any = None) -> Any:
        return self._context.get(key, default)

    @abstractmethod
    def execute(self) -> bool:
        pass
