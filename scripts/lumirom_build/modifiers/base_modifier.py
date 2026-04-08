import os
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    from ..config_loader import ConfigLoader

import logging


class BaseModifier(ABC):
    """Base class for all firmware modification tasks."""

    def __init__(
        self, config: Dict[str, Any], config_loader: Optional["ConfigLoader"] = None
    ):
        self._config = config
        self._config_loader = config_loader
        self.logger = logging.getLogger(self.__class__.__name__)

    @property
    def firm_dir(self) -> str:
        return self._config.get("firm_dir", "FIRMWARE")

    @property
    def ws_root(self) -> str:
        return self._config.get("ws_root", os.getcwd())

    @property
    def tmp_dir(self) -> str:
        return self._config.get("tmp_dir", "TMP") or "/dev/shm/WORK"

    @property
    def device(self) -> str:
        return self._config.get("device", "SM-A325F")

    @abstractmethod
    def apply(self) -> None:
        """Execute the modification step."""
        pass
