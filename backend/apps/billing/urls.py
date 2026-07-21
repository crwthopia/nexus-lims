from rest_framework.routers import SimpleRouter

from apps.billing.views import CustomerInvoiceViewSet, InvoiceViewSet, PaymentViewSet

router = SimpleRouter()
router.register("invoices", InvoiceViewSet, basename="invoice")
router.register("payments", PaymentViewSet, basename="payment")
router.register("my/invoices", CustomerInvoiceViewSet, basename="my-invoice")

urlpatterns = router.urls
