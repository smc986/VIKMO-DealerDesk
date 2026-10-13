
import os
import time
from decimal import Decimal, ROUND_HALF_UP

import requests

from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.utils import timezone

from rest_framework import generics, status
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from openai import OpenAIError

from .assistant import chat_with_dealer
from .models import Product, Inventory, Dealer, Order, OrderItem
from .serializers import (
    ProductSerializer,
    InventoryUpdateSerializer,
    DealerSerializer,
    OrderSerializer,
)
from .forecasting import (
    get_forecast,
    get_reorder_data,
    get_all_reorder_suggestions,
)


# --------------------------------------------------
# COMMON HELPERS
# --------------------------------------------------

def api_error(code, message, http_status, details=None):
    return Response(
        {
            "error": {
                "code": code,
                "message": message,
                "details": details or [],
            }
        },
        status=http_status,
    )


def money(value):
    return Decimal(str(value)).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )


def calculate_line(quantity, unit_price):
    subtotal = money(unit_price * quantity)
    tax = money(subtotal * Decimal("0.18"))
    total = subtotal + tax
    return subtotal, tax, total


def generate_order_number():
    """Generate ORD-YYYYMMDD-NNNN using India-local date."""
    prefix = f"ORD-{timezone.localdate():%Y%m%d}-"

    numbers = Order.objects.filter(
        order_number__startswith=prefix
    ).values_list("order_number", flat=True)

    highest = 0

    for number in numbers:
        suffix = number[len(prefix):]
        if suffix.isdigit():
            highest = max(highest, int(suffix))

    return f"{prefix}{highest + 1:04d}"


def prepare_order_items(items):
    """Validate items and calculate totals using current catalogue prices."""
    if not isinstance(items, list) or not items:
        return None, None, api_error(
            "VALIDATION_ERROR",
            "Order items must be a non-empty list.",
            status.HTTP_400_BAD_REQUEST,
        )

    prepared = []
    seen_skus = set()
    subtotal = Decimal("0.00")
    tax_total = Decimal("0.00")

    for item in items:
        if not isinstance(item, dict):
            return None, None, api_error(
                "VALIDATION_ERROR",
                "Each order item must be an object.",
                status.HTTP_400_BAD_REQUEST,
            )

        sku = item.get("sku")
        quantity = item.get("quantity")

        if not isinstance(sku, str) or not sku.strip():
            return None, None, api_error(
                "VALIDATION_ERROR",
                "Each item must contain a valid SKU.",
                status.HTTP_400_BAD_REQUEST,
            )

        sku = sku.strip()

        if sku in seen_skus:
            return None, None, api_error(
                "VALIDATION_ERROR",
                f"SKU '{sku}' appears more than once.",
                status.HTTP_400_BAD_REQUEST,
            )

        seen_skus.add(sku)

        if (
            isinstance(quantity, bool)
            or not isinstance(quantity, int)
            or quantity < 1
        ):
            return None, None, api_error(
                "VALIDATION_ERROR",
                f"Quantity for SKU '{sku}' must be an integer of at least 1.",
                status.HTTP_400_BAD_REQUEST,
            )

        try:
            product = Product.objects.get(sku=sku)
        except Product.DoesNotExist:
            return None, None, api_error(
                "VALIDATION_ERROR",
                f"Product SKU '{sku}' does not exist.",
                status.HTTP_400_BAD_REQUEST,
            )

        line_subtotal, line_tax, line_total = calculate_line(
            quantity, product.price
        )

        subtotal += line_subtotal
        tax_total += line_tax

        prepared.append({
            "product": product,
            "quantity": quantity,
            "unit_price": product.price,
            "line_subtotal": line_subtotal,
            "line_tax": line_tax,
            "line_total": line_total,
        })

    totals = {
        "subtotal": money(subtotal),
        "tax_total": money(tax_total),
        "grand_total": money(subtotal + tax_total),
    }

    return prepared, totals, None


def save_order_items(order, prepared, totals):
    order.items.all().delete()

    for item in prepared:
        OrderItem.objects.create(
            order=order,
            product=item["product"],
            quantity=item["quantity"],
            unit_price=item["unit_price"],
            line_subtotal=item["line_subtotal"],
            line_tax=item["line_tax"],
            line_total=item["line_total"],
        )

    order.subtotal = totals["subtotal"]
    order.tax_total = totals["tax_total"]
    order.grand_total = totals["grand_total"]
    order.save(
        update_fields=[
            "subtotal", "tax_total", "grand_total", "updated_at"
        ]
    )


# --------------------------------------------------
# HEALTH CHECK
# --------------------------------------------------

def health(request):
    return JsonResponse({"status": "ok"})


# --------------------------------------------------
# PAGINATION
# --------------------------------------------------

class ProductPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


# --------------------------------------------------
# PRODUCT APIs
# --------------------------------------------------

class ProductListCreateView(generics.ListCreateAPIView):
    queryset = Product.objects.all().order_by("sku")
    serializer_class = ProductSerializer
    pagination_class = ProductPagination

    def get_queryset(self):
        queryset = super().get_queryset()

        search = self.request.query_params.get("search")
        category = self.request.query_params.get("category")
        vehicle = self.request.query_params.get("vehicle")

        if search:
            queryset = queryset.filter(
                Q(sku__icontains=search)
                | Q(name__icontains=search)
                | Q(brand__icontains=search)
            )

        if category:
            queryset = queryset.filter(category__iexact=category)

        if vehicle:
            queryset = queryset.filter(
                vehicle_fitment__icontains=vehicle
            )

        return queryset



class ProductDetailView(generics.RetrieveUpdateAPIView):
    queryset = Product.objects.all()
    serializer_class = ProductSerializer
    lookup_field = "sku"
    lookup_url_kwarg = "sku"

    def get_object(self):
        sku = self.kwargs["sku"]
        try:
            return Product.objects.get(sku=sku)
        except Product.DoesNotExist:
            from rest_framework.exceptions import NotFound
            raise NotFound(
                detail={
                    "error": {
                        "code": "NOT_FOUND",
                        "message": f"Product '{sku}' was not found.",
                        "details": [],
                    }
                }
            )


# --------------------------------------------------
# INVENTORY API
# --------------------------------------------------

class InventoryUpdateView(APIView):
    def put(self, request, sku):
        with transaction.atomic():
            try:
                product = Product.objects.select_for_update().get(sku=sku)
            except Product.DoesNotExist:
                return api_error(
                    "NOT_FOUND",
                    f"Product '{sku}' was not found.",
                    status.HTTP_404_NOT_FOUND,
                )

            serializer = InventoryUpdateSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)

            quantity = serializer.validated_data["quantity"]
            reason = serializer.validated_data.get("reason", "")

            product.stock = quantity
            product.save(update_fields=["stock"])

            Inventory.objects.create(
                product=product,
                quantity=quantity,
                reason=reason,
            )

        return Response({
            "sku": product.sku,
            "quantity": product.stock,
        })


# --------------------------------------------------
# DEALER APIs
# --------------------------------------------------

class DealerListCreateView(generics.ListCreateAPIView):
    queryset = Dealer.objects.all().order_by("id")
    serializer_class = DealerSerializer
    pagination_class = ProductPagination

    def create(self, request, *args, **kwargs):
        code = request.data.get("dealer_code")

        if code and Dealer.objects.filter(dealer_code=code).exists():
            return api_error(
                "DUPLICATE",
                "A dealer with this dealer_code already exists.",
                status.HTTP_409_CONFLICT,
            )

        return super().create(request, *args, **kwargs)


class DealerDetailView(generics.RetrieveAPIView):
    queryset = Dealer.objects.all()
    serializer_class = DealerSerializer


# --------------------------------------------------
# ORDER LIST AND CREATE
# --------------------------------------------------

class OrderListCreateView(APIView):
    def get(self, request):
        orders = (
            Order.objects.select_related("dealer")
            .prefetch_related("items__product")
            .order_by("-created_at")
        )

        dealer_id = request.query_params.get("dealer_id")
        order_status = request.query_params.get("status")

        if dealer_id:
            orders = orders.filter(dealer_id=dealer_id)

        if order_status:
            orders = orders.filter(status=order_status.upper())

        paginator = ProductPagination()
        page = paginator.paginate_queryset(orders, request)

        return paginator.get_paginated_response(
            OrderSerializer(page, many=True).data
        )

    def post(self, request):
        dealer_id = request.data.get("dealer_id")

        if dealer_id is None:
            return api_error(
                "VALIDATION_ERROR",
                "dealer_id is required.",
                status.HTTP_400_BAD_REQUEST,
            )

        try:
            dealer = Dealer.objects.get(pk=dealer_id)
        except (Dealer.DoesNotExist, ValueError, TypeError):
            return api_error(
                "VALIDATION_ERROR",
                "The specified dealer does not exist.",
                status.HTTP_400_BAD_REQUEST,
            )

        prepared, totals, error = prepare_order_items(
            request.data.get("items")
        )

        if error:
            return error

        with transaction.atomic():
            order = Order.objects.create(
                order_number=generate_order_number(),
                dealer=dealer,
                status="DRAFT",
                **totals,
            )

            save_order_items(order, prepared, totals)

        order.refresh_from_db()

        return Response(
            OrderSerializer(order).data,
            status=status.HTTP_201_CREATED,
        )


# --------------------------------------------------
# ORDER DETAIL AND EDIT
# --------------------------------------------------

class OrderDetailView(generics.RetrieveUpdateAPIView):
    queryset = (
        Order.objects.select_related("dealer")
        .prefetch_related("items__product")
    )
    serializer_class = OrderSerializer
    lookup_field = "order_number"
    lookup_url_kwarg = "order_number"
    http_method_names = ["get", "put", "head", "options"]

    def update(self, request, *args, **kwargs):
        with transaction.atomic():
            try:
                order = Order.objects.select_for_update().get(
                    order_number=kwargs["order_number"]
                )
            except Order.DoesNotExist:
                return api_error(
                    "NOT_FOUND",
                    "Order not found.",
                    status.HTTP_404_NOT_FOUND,
                )

            if order.status != "DRAFT":
                return api_error(
                    "ORDER_LOCKED",
                    "Only DRAFT orders can be edited.",
                    status.HTTP_409_CONFLICT,
                )

            prepared, totals, error = prepare_order_items(
                request.data.get("items")
            )

            if error:
                return error

            save_order_items(order, prepared, totals)

        order.refresh_from_db()
        return Response(OrderSerializer(order).data)


# --------------------------------------------------
# ORDER STATUS ACTIONS
# --------------------------------------------------

class OrderActionView(APIView):
    action_name = ""

    def post(self, request, order_number):
        with transaction.atomic():
            try:
                order = (
                    Order.objects.select_for_update()
                    .select_related("dealer")
                    .get(order_number=order_number)
                )
            except Order.DoesNotExist:
                return api_error(
                    "NOT_FOUND",
                    "Order not found.",
                    status.HTTP_404_NOT_FOUND,
                )

            if self.action_name == "confirm":
                if order.status != "DRAFT":
                    return api_error(
                        "INVALID_TRANSITION",
                        "Only DRAFT orders can be confirmed.",
                        status.HTTP_409_CONFLICT,
                    )

                # Lock all products in a stable order to reduce
                # the chance of concurrent stock updates.
                items = list(
                    order.items.select_related("product").order_by(
                        "product__sku"
                    )
                )
                products = {}

                for item in items:
                    product = Product.objects.select_for_update().get(
                        sku=item.product.sku
                    )
                    products[product.sku] = product

                shortages = []

                for item in items:
                    product = products[item.product.sku]
                    if product.stock < item.quantity:
                        shortages.append({
                            "sku": product.sku,
                            "requested": item.quantity,
                            "available": product.stock,
                        })

                if shortages:
                    return api_error(
                        "INSUFFICIENT_STOCK",
                        "There is insufficient stock for one or more items.",
                        status.HTTP_409_CONFLICT,
                        shortages,
                    )

                # Recalculate prices from the current catalogue
                # and save the price used for the confirmed order.
                prepared = []
                subtotal = Decimal("0.00")
                tax_total = Decimal("0.00")

                for item in items:
                    product = products[item.product.sku]
                    line_subtotal, line_tax, line_total = calculate_line(
                        item.quantity, product.price
                    )

                    prepared.append({
                        "product": product,
                        "quantity": item.quantity,
                        "unit_price": product.price,
                        "line_subtotal": line_subtotal,
                        "line_tax": line_tax,
                        "line_total": line_total,
                    })

                    subtotal += line_subtotal
                    tax_total += line_tax

                totals = {
                    "subtotal": money(subtotal),
                    "tax_total": money(tax_total),
                    "grand_total": money(subtotal + tax_total),
                }

                save_order_items(order, prepared, totals)

                for item in prepared:
                    product = products[item["product"].sku]
                    product.stock -= item["quantity"]
                    product.save(update_fields=["stock"])

                order.status = "CONFIRMED"
                order.save(update_fields=["status", "updated_at"])

            elif self.action_name == "dispatch":
                if order.status != "CONFIRMED":
                    return api_error(
                        "INVALID_TRANSITION",
                        "Only CONFIRMED orders can be dispatched.",
                        status.HTTP_409_CONFLICT,
                    )

                order.status = "DISPATCHED"
                order.save(update_fields=["status", "updated_at"])

            elif self.action_name == "deliver":
                if order.status != "DISPATCHED":
                    return api_error(
                        "INVALID_TRANSITION",
                        "Only DISPATCHED orders can be delivered.",
                        status.HTTP_409_CONFLICT,
                    )

                order.status = "DELIVERED"
                order.save(update_fields=["status", "updated_at"])

            elif self.action_name == "cancel":
                if order.status not in ["DRAFT", "CONFIRMED"]:
                    return api_error(
                        "INVALID_TRANSITION",
                        "Only DRAFT or CONFIRMED orders can be cancelled.",
                        status.HTTP_409_CONFLICT,
                    )

                # Restore stock only when cancelling a confirmed order.
                if order.status == "CONFIRMED":
                    items = list(
                        order.items.select_related("product").order_by(
                            "product__sku"
                        )
                    )

                    for item in items:
                        product = Product.objects.select_for_update().get(
                            sku=item.product.sku
                        )
                        product.stock += item.quantity
                        product.save(update_fields=["stock"])

                order.status = "CANCELLED"
                order.save(update_fields=["status", "updated_at"])

            else:
                return api_error(
                    "INVALID_ACTION",
                    "Unsupported order action.",
                    status.HTTP_400_BAD_REQUEST,
                )

            order.refresh_from_db()
            return Response({
    "order": OrderSerializer(order).data
})

class OrderConfirmView(OrderActionView):
    action_name = "confirm"


class OrderDispatchView(OrderActionView):
    action_name = "dispatch"


class OrderDeliverView(OrderActionView):
    action_name = "deliver"


class OrderCancelView(OrderActionView):
    action_name = "cancel"


# --------------------------------------------------
# SUPPLIER SYNCHRONIZATION
# --------------------------------------------------

class SupplierSyncView(APIView):
    def post(self, request):
        base_url = os.getenv("SUPPLIER_API_URL", "").rstrip("/")
        api_key = os.getenv("SUPPLIER_API_KEY", "")

        if not base_url or not api_key:
            return api_error(
                "SUPPLIER_UNAVAILABLE",
                "Supplier API configuration is missing.",
                status.HTTP_502_BAD_GATEWAY,
            )

        headers = {"X-Api-Key": api_key}
        cursor = None
        pages_fetched = 0
        requests_made = 0
        supplier_rows = []

        # Fetch every page before modifying the database. This keeps
        # supplier failures from causing a partial catalogue update.
        while True:
            params = {"limit": 20}
            if cursor:
                params["cursor"] = cursor

            response = None

            for attempt in range(5):
                requests_made += 1

                try:
                    response = requests.get(
                        f"{base_url}/v1/products",
                        headers=headers,
                        params=params,
                        timeout=20,
                    )
                except requests.RequestException:
                    if attempt == 4:
                        return api_error(
                            "SUPPLIER_UNAVAILABLE",
                            "Could not connect to the supplier API.",
                            status.HTTP_502_BAD_GATEWAY,
                        )
                    time.sleep(min(2 ** attempt, 8))
                    continue

                if response.status_code == 429 or (
                    500 <= response.status_code < 600
                ):
                    if attempt == 4:
                        return api_error(
                            "SUPPLIER_UNAVAILABLE",
                            "Supplier API failed after retries.",
                            status.HTTP_502_BAD_GATEWAY,
                        )

                    if response.status_code == 429:
                        retry_after = response.headers.get(
                            "Retry-After", "1"
                        )
                        try:
                            wait_seconds = min(
                                max(float(retry_after), 0), 30
                            )
                        except ValueError:
                            wait_seconds = 1
                    else:
                        wait_seconds = min(2 ** attempt, 8)

                    time.sleep(wait_seconds)
                    continue

                if not response.ok:
                    return api_error(
                        "SUPPLIER_UNAVAILABLE",
                        "Supplier API returned an error.",
                        status.HTTP_502_BAD_GATEWAY,
                    )

                break

            try:
                payload = response.json()
            except (ValueError, AttributeError):
                return api_error(
                    "SUPPLIER_UNAVAILABLE",
                    "Supplier API returned invalid JSON.",
                    status.HTTP_502_BAD_GATEWAY,
                )

            if isinstance(payload, list):
                rows = payload
                next_cursor = None
            elif isinstance(payload, dict):
                rows = (
                    payload.get("results")
                    or payload.get("products")
                    or payload.get("items")
                    or []
                )
                next_cursor = (
                    payload.get("next_cursor")
                    or payload.get("next")
                    or payload.get("cursor")
                )
            else:
                return api_error(
                    "SUPPLIER_UNAVAILABLE",
                    "Supplier API returned an unexpected response.",
                    status.HTTP_502_BAD_GATEWAY,
                )

            if not isinstance(rows, list):
                return api_error(
                    "SUPPLIER_UNAVAILABLE",
                    "Supplier product list is invalid.",
                    status.HTTP_502_BAD_GATEWAY,
                )

            supplier_rows.extend(rows)
            pages_fetched += 1

            if not next_cursor:
                break

            # Some APIs return a URL in "next"; this endpoint expects
            # a cursor value, not a complete URL.
            if isinstance(next_cursor, str) and next_cursor.startswith("http"):
                from urllib.parse import urlparse, parse_qs

                parsed = parse_qs(urlparse(next_cursor).query)
                next_cursor = parsed.get("cursor", [None])[0]

                if not next_cursor:
                    break

            cursor = next_cursor

        # Keep the newest supplier record for each SKU.
        latest_by_sku = {}
        rejected = 0

        for row in supplier_rows:
            if not isinstance(row, dict):
                rejected += 1
                continue

            sku = row.get("sku")
            price_value = row.get("price")

            if not isinstance(sku, str) or not sku.strip():
                rejected += 1
                continue

            try:
                price_decimal = Decimal(str(price_value))
            except Exception:
                rejected += 1
                continue

            if (
                not price_decimal.is_finite()
                or price_decimal <= 0
                or price_decimal != price_decimal.quantize(
                    Decimal("0.01")
                )
                or price_decimal > Decimal("9999999999.99")
            ):
                rejected += 1
                continue

            sku = sku.strip()
            row = dict(row)
            row["sku"] = sku
            row["price"] = price_decimal

            previous = latest_by_sku.get(sku)

            if previous is None or str(row.get("updated_at", "")) >= str(
                previous.get("updated_at", "")
            ):
                if previous is not None:
                    rejected += 1
                latest_by_sku[sku] = row
            else:
                rejected += 1

        created = 0
        updated = 0
        unchanged = 0

        try:
            with transaction.atomic():
                for sku, row in latest_by_sku.items():
                    defaults = {
                        "name": row.get("name", ""),
                        "category": row.get("category", ""),
                        "brand": row.get("brand", ""),
                        "vehicle_fitment": row.get("vehicle_fitment", ""),
                        "description": row.get("description", ""),
                        "price": row["price"],
                    }

                    product = Product.objects.filter(sku=sku).first()

                    if product is None:
                        Product.objects.create(
                            sku=sku,
                            stock=0,
                            **defaults,
                        )
                        created += 1
                        continue

                    changed_fields = []

                    for field, value in defaults.items():
                        if getattr(product, field) != value:
                            setattr(product, field, value)
                            changed_fields.append(field)

                    if changed_fields:
                        product.save(update_fields=changed_fields)
                        updated += 1
                    else:
                        unchanged += 1

        except Exception:
            return api_error(
                "SUPPLIER_UNAVAILABLE",
                "Supplier catalogue changes could not be saved.",
                status.HTTP_502_BAD_GATEWAY,
            )

        return Response({
            "created": created,
            "updated": updated,
            "unchanged": unchanged,
            "rejected": rejected,
            "pages_fetched": pages_fetched,
            "requests_made": requests_made,
        })


# --------------------------------------------------
# AI DEALER ASSISTANT
# --------------------------------------------------

class DealerAssistantChatView(APIView):
    def post(self, request):
        message = request.data.get("message")

        if not isinstance(message, str) or not message.strip():
            return api_error(
                "VALIDATION_ERROR",
                "A non-empty message is required.",
                status.HTTP_400_BAD_REQUEST,
            )

        try:
            result = chat_with_dealer(request, message.strip())
            return Response(result)

        except RuntimeError:
            return api_error(
                "ASSISTANT_NOT_CONFIGURED",
                "The assistant API key is not configured.",
                status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        except OpenAIError:
            return api_error(
                "ASSISTANT_PROVIDER_ERROR",
                "The AI provider request failed.",
                status.HTTP_502_BAD_GATEWAY,
            )


# --------------------------------------------------
# FORECAST API
# --------------------------------------------------

class ForecastView(APIView):
    def get(self, request, sku):
        product = Product.objects.filter(sku__iexact=sku).first()

        if not product:
            return api_error(
                "NOT_FOUND",
                "Product not found.",
                status.HTTP_404_NOT_FOUND,
            )

        forecast = get_forecast(product.sku)

        if forecast is None:
            return api_error(
                "NOT_FOUND",
                "Forecast not found.",
                status.HTTP_404_NOT_FOUND,
            )

        return Response({
            "sku": product.sku,
            "forecast": forecast,
        })


class ReorderSuggestionsView(APIView):
    def get(self, request):
        return Response({
            "results": get_all_reorder_suggestions()
        })
