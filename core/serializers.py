
from rest_framework import serializers
from .models import Product, Dealer, Order, OrderItem


class DealerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Dealer
        fields = [
            "id", "dealer_code", "name", "city",
            "phone", "email", "gstin", "credit_limit",
        ]
        read_only_fields = ["id"]


class ProductSerializer(serializers.ModelSerializer):
    price = serializers.DecimalField(
        max_digits=10, decimal_places=2, coerce_to_string=True
    )

    class Meta:
        model = Product
        fields = [
            "sku", "name", "category", "brand",
            "vehicle_fitment", "price", "stock", "description",
        ]
        read_only_fields = ["stock"]


class InventoryUpdateSerializer(serializers.Serializer):
    quantity = serializers.IntegerField(min_value=0)
    reason = serializers.CharField(
        required=False, allow_blank=True, default=""
    )


class OrderItemSerializer(serializers.ModelSerializer):
    sku = serializers.CharField(source="product.sku", read_only=True)
    name = serializers.CharField(source="product.name", read_only=True)

    unit_price = serializers.DecimalField(
        max_digits=12, decimal_places=2, coerce_to_string=True
    )
    line_subtotal = serializers.DecimalField(
        max_digits=12, decimal_places=2, coerce_to_string=True
    )
    line_tax = serializers.DecimalField(
        max_digits=12, decimal_places=2, coerce_to_string=True
    )
    line_total = serializers.DecimalField(
        max_digits=12, decimal_places=2, coerce_to_string=True
    )

    class Meta:
        model = OrderItem
        fields = [
            "sku", "name", "quantity", "unit_price",
            "line_subtotal", "line_tax", "line_total",
        ]



class OrderSerializer(serializers.ModelSerializer):
    dealer_id = serializers.IntegerField(
        source="dealer.id", read_only=True
    )
    dealer = DealerSerializer(read_only=True)
    items = OrderItemSerializer(many=True, read_only=True)

    subtotal = serializers.DecimalField(
        max_digits=12, decimal_places=2, coerce_to_string=True
    )
    tax_total = serializers.DecimalField(
        max_digits=12, decimal_places=2, coerce_to_string=True
    )
    grand_total = serializers.DecimalField(
        max_digits=12, decimal_places=2, coerce_to_string=True
    )

    class Meta:
        model = Order
        fields = [
            "order_number",
            "dealer_id",
            "dealer",
            "status",
            "items",
            "subtotal",
            "tax_total",
            "grand_total",
            "created_at",
            "updated_at",
        ]
