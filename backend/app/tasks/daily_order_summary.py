"""Send the previous Tehran calendar day's order report to Telegram."""

import logging
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import requests
from celery import shared_task
from django.conf import settings
from django.db.models import Count, Exists, IntegerField, OuterRef, Q, Subquery, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from app.models import (
    AccountingEntry,
    Order,
    Product,
    ProductColor,
    ProductSize,
    ProductVariant,
    PurchaseTransaction,
)

logger = logging.getLogger(__name__)
LOW_STOCK_LIMIT = 3


def prior_tehran_day(now=None):
    """Return a half-open window [midnight yesterday, midnight today)."""
    local_today = timezone.localtime(now or timezone.now(), ZoneInfo("Asia/Tehran")).date()
    zone = ZoneInfo("Asia/Tehran")
    start = datetime.combine(local_today - timedelta(days=1), time.min, tzinfo=zone)
    end = datetime.combine(local_today, time.min, tzinfo=zone)
    return start, end


def low_stock_product_count():
    """Use base stock for plain products and active variant stock for optioned ones."""
    variant_totals = (
        ProductVariant.objects.filter(product_id=OuterRef("pk"), is_active=True)
        .order_by()
        .values("product_id")
        .annotate(total=Sum("stock"))
        .values("total")[:1]
    )
    products = Product.objects.filter(is_active=True).annotate(
        has_colors=Exists(ProductColor.objects.filter(product_id=OuterRef("pk"))),
        has_sizes=Exists(ProductSize.objects.filter(product_id=OuterRef("pk"))),
        variant_stock=Coalesce(
            Subquery(variant_totals, output_field=IntegerField()), Value(0)
        ),
    )
    return products.filter(
        Q(has_colors=False, has_sizes=False, stock__lte=LOW_STOCK_LIMIT)
        | Q(has_colors=True, variant_stock__lte=LOW_STOCK_LIMIT)
        | Q(has_sizes=True, variant_stock__lte=LOW_STOCK_LIMIT)
    ).count()


def build_summary(start, end):
    new_orders = Order.objects.filter(created_at__gte=start, created_at__lt=end)
    order_statuses = dict(
        new_orders.order_by().values("status").annotate(count=Count("pk")).values_list("status", "count")
    )
    payment_statuses = dict(
        PurchaseTransaction.objects.filter(
            order__created_at__gte=start, order__created_at__lt=end
        )
        .order_by()
        .values("status")
        .annotate(count=Count("pk"))
        .values_list("status", "count")
    )
    revenue = (
        AccountingEntry.objects.filter(
            entry_type=AccountingEntry.EntryType.INCOME,
            order__isnull=False,
            occurred_at__gte=start,
            occurred_at__lt=end,
        ).aggregate(total=Sum("amount_toman"))["total"]
        or 0
    )
    local_date = start.strftime("%Y-%m-%d")
    lines = [
        f"DigiGadg — {local_date} (Asia/Tehran)",
        f"New orders: {sum(order_statuses.values()):,}",
        f"Paid revenue: {revenue:,} toman",
        "Order statuses (new orders, current):",
    ]
    lines.extend(f"  {status}: {order_statuses.get(status, 0):,}" for status in Order.Status.values)
    lines.append("Payment attempts for new orders (current):")
    lines.extend(
        f"  {status}: {payment_statuses.get(status, 0):,}"
        for status in PurchaseTransaction.Status.values
    )
    lines.append(f"Low-stock active products (0–{LOW_STOCK_LIMIT}): {low_stock_product_count():,}")
    return "\n".join(lines), sum(order_statuses.values())


@shared_task(ignore_result=True)
def send_daily_order_summary():
    token = settings.TELEGRAM_BOT_TOKEN
    chat_id = settings.TELEGRAM_CHAT_ID
    if not token or not chat_id:
        logger.error("Daily order summary failed: Telegram credentials are missing")
        raise RuntimeError("Telegram credentials are not configured")

    try:
        start, end = prior_tehran_day()
        message, order_count = build_summary(start, end)
        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data={"chat_id": chat_id, "text": message},
            timeout=15,
        )
        response.raise_for_status()
        if not response.json().get("ok"):
            raise RuntimeError("Telegram rejected the message")
    except Exception as exc:
        # requests exceptions can include the URL, which contains the bot token.
        logger.error("Daily order summary failed (%s)", type(exc).__name__)
        raise RuntimeError("Daily order summary failed") from None

    logger.info("Daily order summary sent for %s: %s new orders", start.date(), order_count)

