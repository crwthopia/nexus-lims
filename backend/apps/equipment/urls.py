from rest_framework.routers import SimpleRouter

from apps.equipment.views import CalibrationRecordViewSet, InstrumentViewSet, StandardReagentViewSet

router = SimpleRouter()
router.register("standard-reagents", StandardReagentViewSet, basename="standardreagent")
router.register("instruments", InstrumentViewSet, basename="instrument")
router.register("calibration-records", CalibrationRecordViewSet, basename="calibrationrecord")

urlpatterns = router.urls
