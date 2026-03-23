"""
Intel Sweep — Notification Channels

Delivers scored items to configured channels with approve/discard controls.
"""

import logging
import os
from abc import ABC, abstractmethod

logger = logging.getLogger("intel-sweep.notifier")


class NotifierRegistry:
    """Routes notifications to configured channels based on topic filters."""

    def __init__(self, configs: list[dict]):
        self._notifiers: list[tuple[BaseNotifier, list[str] | None]] = []
        for cfg in configs:
            notifier = _build_notifier(cfg)
            topic_filter = cfg.get("topics")  # None = all topics
            self._notifiers.append((notifier, topic_filter))

    async def notify(self, item: dict, topic: dict) -> None:
        for notifier, topic_filter in self._notifiers:
            if topic_filter and topic["id"] not in topic_filter:
                continue
            try:
                await notifier.send(item)
            except Exception as e:
                logger.error(f"Notification failed ({notifier.__class__.__name__}): {e}")


class BaseNotifier(ABC):
    @abstractmethod
    async def send(self, item: dict) -> None: ...


class SlackNotifier(BaseNotifier):
    def __init__(self, config: dict):
        self.webhook_url = os.environ[config["webhook_env"]]
        self.format = config.get("format", "compact")
        self.include_score = config.get("include_score", True)
        self.include_summary = config.get("include_summary", True)

    async def send(self, item: dict) -> None:
        import aiohttp

        blocks = self._build_blocks(item)
        payload = {"blocks": blocks}

        async with aiohttp.ClientSession() as session:
            async with session.post(self.webhook_url, json=payload) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    logger.error(f"Slack webhook error {resp.status}: {text}")

    def _build_blocks(self, item: dict) -> list[dict]:
        score_str = f" · Score: {item['score']:.2f}" if self.include_score else ""
        status_emoji = "🟢" if item["status"] == "auto_approved" else "🔵"

        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"{status_emoji} *<{item['url']}|{item['title']}>*\n"
                        f"Topic: {item['topic_name']} · Keyword: `{item['keyword']}`{score_str}"
                    ),
                },
            },
        ]

        if self.include_summary and item.get("snippet"):
            blocks.append(
                {
                    "type": "context",
                    "elements": [
                        {"type": "mrkdwn", "text": item["snippet"][:300]},
                    ],
                }
            )

        gamut_lines = _format_gamut_verification(item)
        if gamut_lines:
            blocks.append(
                {
                    "type": "context",
                    "elements": [{"type": "mrkdwn", "text": gamut_lines}],
                }
            )

        if self.format == "detailed":
            blocks.append({"type": "divider"})

        return blocks


class TelegramNotifier(BaseNotifier):
    def __init__(self, config: dict):
        self.bot_token = os.environ[config["bot_token_env"]]
        self.chat_id = os.environ[config["chat_id_env"]]
        self.format = config.get("format", "compact")

    async def send(self, item: dict) -> None:
        import aiohttp

        status_emoji = "🟢" if item["status"] == "auto_approved" else "🔵"
        text = (
            f"{status_emoji} <b>{item['title']}</b>\n"
            f"Score: {item['score']:.2f} · {item['topic_name']}\n"
            f"<a href=\"{item['url']}\">Read →</a>"
        )

        if self.format == "detailed" and item.get("snippet"):
            text += f"\n\n{item['snippet'][:300]}"

        gamut_lines = _format_gamut_verification(item)
        if gamut_lines:
            text += f"\n{gamut_lines}"

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    logger.error(f"Telegram error {resp.status}: {text}")


class WebhookNotifier(BaseNotifier):
    """Generic webhook — post JSON payload to any URL."""

    def __init__(self, config: dict):
        self.url = os.environ[config["url_env"]]

    async def send(self, item: dict) -> None:
        import aiohttp

        async with aiohttp.ClientSession() as session:
            async with session.post(self.url, json=item) as resp:
                if resp.status >= 400:
                    logger.error(f"Webhook error {resp.status}")


def _format_gamut_verification(item: dict) -> str:
    """
    Format Gamut verification results as a compact badge line for notifications.

    Example output:
      Gamut: 🔴 BlueShark Pte Ltd — STRUCK OFF (CVI: 62) · 🟢 Acme Corp — ACTIVE (CVI: 91)
    """
    verifications = item.get("gamut_verification")
    if not verifications:
        return ""

    STATUS_EMOJI = {
        "active": "🟢",
        "live": "🟢",
        "struck_off": "🔴",
        "dissolved": "🔴",
        "inactive": "🟡",
    }

    parts = []
    for v in verifications:
        status = (v.get("registry_status") or "unknown").lower()
        emoji = STATUS_EMOJI.get(status, "⚪")
        cvi = v.get("confidence_score")
        cvi_str = f" (CVI: {cvi})" if cvi is not None else ""
        parts.append(f"{emoji} {v['entity_name']} — {status.upper()}{cvi_str}")

    return "Gamut: " + " · ".join(parts)


def _build_notifier(config: dict) -> BaseNotifier:
    channel = config["channel"]
    builders = {
        "slack": SlackNotifier,
        "telegram": TelegramNotifier,
        "webhook": WebhookNotifier,
    }
    if channel not in builders:
        raise ValueError(f"Unknown notification channel: {channel}. Use: {list(builders)}")
    return builders[channel](config)
