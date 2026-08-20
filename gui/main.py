"""BillboardAI GUI launcher.

Run with:  python -m gui.main
"""

from __future__ import annotations

import logging
import os
import sys

from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import QApplication

from gui.controllers.app_controller import BillboardController
from gui.controllers.batch_generation_controller import BatchGenerationController
from gui.controllers.campaign_review_controller import CampaignReviewController
from gui.controllers.campaign_run_controller import CampaignRunController
from gui.controllers.inventory_controller import InventoryController
from gui.controllers.project_controller import ProjectWorkspaceController
from gui.controllers.prospect_controller import ProspectController
from gui.controllers.smartlead_handoff_controller import SmartleadHandoffController
from gui.models.campaign_review_store import CampaignReviewStore
from gui.models.campaign_run import CampaignRunStore
from gui.models.campaign_assembly import CampaignAssemblyStore
from gui.models.hosted_asset_store import HostedAssetStore
from gui.models.project_store import ProjectStore
from gui.models.prospect_generation_store import ProspectGenerationStore
from gui.models.smartlead_activation_store import SmartleadActivationStore
from gui.models.smartlead_connection import SmartleadConnectionSettings
from gui.models.smartlead_pilot_store import SmartleadPilotStore
from gui.models.smartlead_publication_store import SmartleadPublicationStore
from gui.models.smartlead_run_package import SmartleadRunPackageStore
from gui.models.smartlead_sequence import SequenceChangeStore
from gui.services.asset_hosting import CloudinaryAssetProvider, HostingConnectionSettings
from gui.services.campaign_export import CampaignExportService
from gui.services.campaign_package import CampaignPackageService
from gui.services.campaign_review import CampaignReviewService
from gui.services.campaign_run import CampaignRunService
from gui.services.campaign_assembly import CampaignAssemblyService
from gui.services.hosted_mockups import AssetHostingService
from gui.services.prospect_generation import ProspectGenerationService
from gui.services.smartlead_activation import SmartleadActivationService
from gui.services.smartlead_api import SmartleadApiClient
from gui.services.smartlead_handoff import SmartleadHandoffService
from gui.services.smartlead_pilot import SmartleadPilotService
from gui.services.smartlead_publish import SmartleadPublishService
from gui.services.smartlead_reconciliation import SmartleadReconciliationService
from gui.services.smartlead_run_export import SmartleadRunExportService
from gui.services.smartlead_run_handoff import SmartleadRunHandoffService
from gui.services.smartlead_sequence_readiness import SmartleadSequenceReadinessService
from gui.main_window import MainWindow
from gui.resources import APP_VERSION
from gui.resources.styles import APP_STYLESHEET

logger = logging.getLogger(__name__)

# Path where an application icon can be dropped without code changes.
ICON_DIR = os.path.join(os.path.dirname(__file__), "..", "assets", "icons")
ICON_CANDIDATES = ["billboardai.png", "app.png", "icon.png"]


def _load_icon() -> QIcon | None:
    """Load the application icon if one exists in assets/icons/."""
    for name in ICON_CANDIDATES:
        path = os.path.join(ICON_DIR, name)
        if os.path.isfile(path):
            return QIcon(path)
    return None


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logger.info("Application Started (v%s)", APP_VERSION)

    app = QApplication(sys.argv)
    app.setApplicationName("BillboardAI")
    app.setOrganizationName("BillboardAI")
    app.setApplicationVersion(APP_VERSION)
    app.setStyleSheet(APP_STYLESHEET)

    icon = _load_icon()
    if icon is not None:
        app.setWindowIcon(icon)

    # Ensure default font works on all platforms
    font = QFont("Segoe UI", 13)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    app.setFont(font)

    controller = BillboardController()
    workspace_controller = ProjectWorkspaceController()
    inventory_controller = InventoryController()
    prospect_controller = ProspectController()
    generation_service = ProspectGenerationService(
        prospect_store=prospect_controller.service.store,
        job_store=ProspectGenerationStore(),
        project_store=ProjectStore(),
    )
    batch_controller = BatchGenerationController(prospect_controller=prospect_controller, service=generation_service)
    export_service = CampaignExportService(
        prospect_store=generation_service.prospect_store,
        job_store=generation_service.job_store,
        project_store=generation_service.project_store,
    )
    package_service = CampaignPackageService(export_service=export_service)
    review_store = CampaignReviewStore()
    review_service = CampaignReviewService(
        prospect_store=generation_service.prospect_store,
        export_service=export_service,
        review_store=review_store,
        package_service=package_service,
    )
    review_controller = CampaignReviewController(service=review_service)
    campaign_run_service = CampaignRunService(
        run_store=CampaignRunStore(),
        prospect_store=generation_service.prospect_store,
        job_store=generation_service.job_store,
        project_store=generation_service.project_store,
        review_store=review_store,
        generation_service=generation_service,
        export_service=export_service,
        review_service=review_service,
    )
    campaign_run_controller = CampaignRunController(service=campaign_run_service)
    smartlead_run_service = SmartleadRunHandoffService(
        run_service=campaign_run_service,
        package_store=SmartleadRunPackageStore(),
    )
    api_client = SmartleadApiClient(settings=SmartleadConnectionSettings())
    publication_store = SmartleadPublicationStore()
    hosted_asset_store = HostedAssetStore()
    hosting_service = AssetHostingService(
        provider=CloudinaryAssetProvider(settings=HostingConnectionSettings()),
        asset_store=hosted_asset_store,
    )
    publish_service = SmartleadPublishService(
        api_client=api_client,
        receipt_store=publication_store,
        hosted_asset_store=hosted_asset_store,
    )
    sequence_service = SmartleadSequenceReadinessService(
        api_client=api_client,
        change_store=SequenceChangeStore(),
    )
    reconciliation_service = SmartleadReconciliationService(
        api_client=api_client,
        publication_store=publication_store,
        hosted_asset_store=hosted_asset_store,
        sequence_service=sequence_service,
    )
    activation_service = SmartleadActivationService(
        api_client=api_client,
        reconciliation_service=reconciliation_service,
        activation_store=SmartleadActivationStore(),
        sequence_service=sequence_service,
    )
    pilot_service = SmartleadPilotService(
        pilot_store=SmartleadPilotStore(),
        review_service=review_service,
        handoff_service=SmartleadHandoffService(),
        reconciliation_service=reconciliation_service,
        activation_service=activation_service,
        api_client=api_client,
        sequence_service=sequence_service,
    )
    smartlead_run_export_service = SmartleadRunExportService(
        run_handoff_service=smartlead_run_service,
        hosted_asset_store=hosted_asset_store,
    )
    campaign_assembly_service = CampaignAssemblyService(
        run_service=campaign_run_service,
        run_handoff_service=smartlead_run_service,
        run_export_service=smartlead_run_export_service,
        assembly_store=CampaignAssemblyStore(),
    )
    campaign_run_controller.set_assembly_service(campaign_assembly_service)
    smartlead_controller = SmartleadHandoffController(
        service=SmartleadHandoffService(),
        publish_service=publish_service,
        hosting_service=hosting_service,
        sequence_service=sequence_service,
        reconciliation_service=reconciliation_service,
        activation_service=activation_service,
        pilot_service=pilot_service,
        run_handoff_service=smartlead_run_service,
        run_export_service=smartlead_run_export_service,
    )
    window = MainWindow(
        controller,
        batch_controller,
        review_controller,
        smartlead_controller,
        workspace_controller,
        inventory_controller,
        prospect_controller,
        campaign_run_controller,
    )
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()