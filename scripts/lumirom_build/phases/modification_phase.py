import logging

from ..modifiers.features import (
    DisplayIdUpdaterModifier,
    FeaturesApplierModifier,
    LumiBombsApplierModifier,
    StockConfigApplierModifier,
)
from ..modifiers.framework import FrameworkInstallerModifier, FrameworkPatcherModifier
from ..modifiers.fstab import DisableFbeModifier, PatchFstabErofsModifier
from ..modifiers.removals import (
    DebloatAppsModifier,
    DeviceSpecificRemoverModifier,
    EsimRemoverModifier,
    FabricCryptoRemoverModifier,
    IcccDeleterModifier,
    JdmDebloatModifier,
    VendorDebloaterModifier,
)
from ..modifiers.selinux import CilHashesCheckpointerModifier, SelinuxFixerModifier
from ..modifiers.system import (
    BtLibPatcherModifier,
    DeodexModifier,
    SystemExtFixerModifier,
)
from .base_phase import BasePhase

logger = logging.getLogger(__name__)


class ModificationPhase(BasePhase):
    PHASE_TAG = "MODIFY"

    @property
    def name(self) -> str:
        return "Modification"

    def execute(self) -> bool:
        logger.debug("Entering ModificationPhase.execute")

        modifiers = [
            SystemExtFixerModifier,
            DisableFbeModifier,
            PatchFstabErofsModifier,
            IcccDeleterModifier,
            VendorDebloaterModifier,
            EsimRemoverModifier,
            FabricCryptoRemoverModifier,
            JdmDebloatModifier,
            DebloatAppsModifier,
            DeviceSpecificRemoverModifier,
            FrameworkInstallerModifier,
            StockConfigApplierModifier,
            LumiBombsApplierModifier,
            FeaturesApplierModifier,
            DisplayIdUpdaterModifier,
            DeodexModifier,
            FrameworkPatcherModifier,
            BtLibPatcherModifier,
            SelinuxFixerModifier,
        ]

        for mod_cls in modifiers:
            mod = mod_cls(self._config, self._config_loader)
            mod.apply()

        checkpoint = CilHashesCheckpointerModifier(
            self._config, self._config_loader, "PRE-PACKAGING"
        )
        checkpoint.apply()

        logger.info("Modification phase complete")
        return True
