# Telegram operations notifications

## Setup after deployment

1. In Telegram, open the verified **@BotFather** account, send `/newbot`, and choose a display name and username ending in `bot`. Do not paste the resulting token in chat, Git, screenshots or browser URLs.
2. Open Django admin → **Operations → Telegram settings** (`/admin/operations/telegramsettings/`). Add a settings record, paste the token in the write-only **Bot token** field and save with **Enabled** off. Tokens are encrypted with the existing payment encryption key/secret derivation. Leave the field blank on later edits to retain it.
3. Open the bot's private chat and send `/start`, or add it to a private operations group and send `/start@YourBotUsername` there. The bot must be allowed to send messages. Channels require the bot to have posting permission.
4. On the Telegram settings list, select the settings row and run **Find chat IDs from recent bot messages**. Only chat titles/IDs are displayed, never message bodies. Copy the intended destination ID (groups commonly start with `-100`) into **Chat ID**. For forum groups, optionally specify a message thread/topic ID.
5. Select the notification categories and report timezone (default Asia/Tehran), save and run **Send a connection test to the configured chat**. This explicitly sends one harmless test message and works while automatic alerts are disabled.
6. Once the test arrives, enable alerts. **Telegram notifications** lists queued/sent/dismissed records, attempts and sanitized delivery errors.

If the bot already uses a webhook, `getUpdates` chat discovery is unavailable; enter the destination chat ID directly without removing an existing webhook. There is no automatic group selection or bot-account creation.

Environment variables are also supported: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, optional `TELEGRAM_TIMEZONE`. Without a database settings row, providing valid token/chat values enables event capture. When a settings row exists its Enabled switch/categories govern capture and delivery; blank token/chat fields fall back to environment values. Do not rotate the existing payment/secret encryption key without migrating encrypted credentials.

## Events and data

- New trial, scholarship, teacher and volunteer forms and newsletter subscriptions.
- CRM lead creation, lifecycle changes, trial outcomes/feedback and verified enquiry connection.
- Class booking and cancellation-request states; class and catalog payment states with amount/currency/mode.
- New accounts and safe admin audit events.
- Successful/failed class confirmation, reminder, cancellation and CRM email delivery.
- ERROR-level server summaries containing only logger, exception class and resolved route pattern. Raw log messages, exception strings, tracebacks, request bodies/headers/query strings, passwords, bot/provider tokens, classroom links, learner goals and private notes are never forwarded by this handler.

Events contain source identifiers and protected Django admin links. Applicant names/email/phone are omitted by default; **Include contact details** explicitly enables those three fields for future messages. It never enables free-text notes, uploaded files, DOB or classroom links. Choose a destination appropriate for the data and staff access. The integration is an operational event/ERROR stream, not a copy of every HTTP/debug log or a retrospective export of historical CRM records. Repeated status saves are deduplicated; high-frequency identical runtime errors are grouped per route/logger/exception/minute.

## Delivery, retries and limits

Business requests only enqueue database records; Telegram network requests never occur inside a form or payment operation. Queue writes use an isolated savepoint and fail closed, so a disabled/broken notification integration does not break a booking. An unavailable database cannot persist its own error notification; existing server logs remain the diagnostic fallback.

The existing GitHub Actions reminder workflow calls a separate `/api/academy/internal/telegram/` worker after the email worker. Both endpoints run independently and use the same restricted short-lived workflow identity or configured `CRON_SECRET`. No frontend/session user can call the worker. Runs are approximately every five minutes with GitHub scheduling delays possible; routine alerts are not guaranteed instant. The admin connection test is direct.

The worker leases rows, backs off on API/network errors, respects Telegram `retry_after`, disables link previews and uses plain text. A changed destination does not silently reroute pending messages: each message snapshots chat/topic IDs. **Retry unsent messages using the current destination** explicitly requeues selected rows to the latest configured destination. **Dismiss unsent notifications** suppresses delivery while preserving audit history. Already-sent messages are not resent by these actions. Telegram has no provider idempotency key; a successful API call with a lost response can still result in a rare duplicate on retry.

No live credentials or real test messages are used by the automated tests. Until a bot token, destination and Enabled configuration are supplied, the integration remains inactive and does not capture/send past events retroactively.
