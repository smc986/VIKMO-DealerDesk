
from django.urls import path
from . import views

urlpatterns = [
    path("health/", views.health, name="health"),

    path("products/", views.ProductListCreateView.as_view(), name="product-list-create"),
    path("products/<str:sku>/", views.ProductDetailView.as_view(), name="product-detail"),

    path("inventory/<str:sku>/", views.InventoryUpdateView.as_view(), name="inventory-update"),

    path("dealers/", views.DealerListCreateView.as_view(), name="dealer-list-create"),
    path("dealers/<int:pk>/", views.DealerDetailView.as_view(), name="dealer-detail"),

    path("orders/", views.OrderListCreateView.as_view(), name="order-list-create"),
    path("orders/<str:order_number>/", views.OrderDetailView.as_view(), name="order-detail"),
    path("orders/<str:order_number>/confirm/", views.OrderConfirmView.as_view(), name="order-confirm"),
    path("orders/<str:order_number>/dispatch/", views.OrderDispatchView.as_view(), name="order-dispatch"),
    path("orders/<str:order_number>/deliver/", views.OrderDeliverView.as_view(), name="order-deliver"),
    path("orders/<str:order_number>/cancel/", views.OrderCancelView.as_view(), name="order-cancel"),

    path("sync/supplier/", views.SupplierSyncView.as_view(), name="supplier-sync"),

    path("assistant/chat/", views.DealerAssistantChatView.as_view(), name="assistant-chat"),

    path("forecast/<str:sku>/", views.ForecastView.as_view(), name="forecast"),
    path("reorder-suggestions/", views.ReorderSuggestionsView.as_view(), name="reorder-suggestions"),
]
