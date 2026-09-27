# Daily Telegram order summary

The existing Celery Beat service schedules `app.tasks.daily_order_summary.send_daily_order_summary` at **09:00 Asia/Tehran**. It reads the database directly; no public endpoint is needed.

The report covers the previous Tehran calendar day, from 00:00 inclusive to the following 00:00 exclusive. New orders are counted by `Order.created_at`; their order statuses and linked payment-attempt statuses are shown as they stand when the report runs. Paid revenue is the sum of order-linked `AccountingEntry` income recorded in that day, including payments for orders created earlier. Low stock is a current snapshot of active products with 0–3 units: base stock for products without options, and active variant stock for products with options.

## Production setup

1. Create a Telegram bot with BotFather and obtain its bot token. Send the bot a message (or add it to the destination group/channel), then obtain the destination chat ID.
2. On the deployment server, set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in the root `.env` file. This file is ignored by Git. Keep it readable only by the deployment account. Do not place the values in `.env.example` or Docker Compose source.
3. Rebuild and restart the backend, Celery worker, and Celery Beat services with `docker compose -f docker-compose.prod.yml up -d --build backend celery celery-beat`. Ensure only one Beat instance is running to avoid duplicate messages.
4. Check the `celery` and `celery-beat` container logs for the task's success or failure line. The task logs no bot token, chat ID, Telegram response body, or customer details.

For a one-time delivery check after setting secrets, run `docker compose -f docker-compose.prod.yml exec backend python manage.py shell -c "from app.tasks.daily_order_summary import send_daily_order_summary; send_daily_order_summary()"`. This sends a real report to the configured chat; it does not change orders.

