
import csv
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import Product, Dealer


class Command(BaseCommand):
    help = "Load catalogue and dealer data into the database safely."

    @transaction.atomic
    def handle(self, *args, **options):
        data_dir = Path(settings.DATA_DIR)

        catalogue_file = data_dir / "catalogue.csv"
        dealers_file = data_dir / "dealers.csv"

        for file_path in (catalogue_file, dealers_file):
            if not file_path.is_file():
                raise CommandError(f"Required file not found: {file_path}")

        products_created = 0
        products_updated = 0

        with catalogue_file.open(
            "r", encoding="utf-8-sig", newline=""
        ) as file:
            reader = csv.DictReader(file)

            for row in reader:
                sku = row["sku"].strip()

                if not sku:
                    continue

                _, created = Product.objects.update_or_create(
                    sku=sku,
                    defaults={
                        "name": row["name"].strip(),
                        "category": row["category"].strip(),
                        "brand": row["brand"].strip(),
                        "vehicle_fitment": row["vehicle_fitment"].strip(),
                        "price": Decimal(row["price"]),
                        "stock": int(row["stock"]),
                        "description": row.get("description", "").strip(),
                    },
                )

                if created:
                    products_created += 1
                else:
                    products_updated += 1

        dealers_created = 0
        dealers_updated = 0

        with dealers_file.open(
            "r", encoding="utf-8-sig", newline=""
        ) as file:
            reader = csv.DictReader(file)

            for row in reader:
                dealer_code = row["dealer_code"].strip()

                if not dealer_code:
                    continue

                _, created = Dealer.objects.update_or_create(
                    dealer_code=dealer_code,
                    defaults={
                        "name": row["name"].strip(),
                        "city": row.get("city", "").strip(),
                        "phone": row.get("phone", "").strip(),
                        "email": row.get("email", "").strip(),
                        "gstin": row.get("gstin", "").strip(),
                        "credit_limit": Decimal(
                            row.get("credit_limit") or "0"
                        ),
                    },
                )

                if created:
                    dealers_created += 1
                else:
                    dealers_updated += 1

        self.stdout.write(
            self.style.SUCCESS(
                "Seed completed successfully!\n"
                f"Products created: {products_created}\n"
                f"Products updated: {products_updated}\n"
                f"Dealers created: {dealers_created}\n"
                f"Dealers updated: {dealers_updated}"
            )
        )
