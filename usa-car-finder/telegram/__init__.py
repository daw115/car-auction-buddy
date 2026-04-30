"""
Telegram Bot - wysyłanie raportów i obsługa zatwierdzania.
"""
import os
import ssl
import asyncio
from typing import Optional
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


def _ssl_context():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


class TelegramBot:

    def __init__(self):
        self.bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID")

        if not self.bot_token or not self.chat_id:
            raise ValueError("TELEGRAM_BOT_TOKEN i TELEGRAM_CHAT_ID muszą być ustawione w .env")

        self.base_url = f"https://api.telegram.org/bot{self.bot_token}"
        self.pending_approval = False

    async def send_message(self, text: str, reply_markup: Optional[dict] = None, parse_mode: Optional[str] = None):
        import aiohttp

        url = f"{self.base_url}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        if parse_mode:
            payload["parse_mode"] = parse_mode

        connector = aiohttp.TCPConnector(ssl=_ssl_context())
        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.post(url, json=payload) as response:
                if response.status != 200:
                    error = await response.text()
                    raise Exception(f"Błąd wysyłania wiadomości: {error}")
                return await response.json()

    async def send_document(self, file_path: str, caption: Optional[str] = None):
        import aiohttp

        url = f"{self.base_url}/sendDocument"

        with open(file_path, 'rb') as file:
            data = aiohttp.FormData()
            data.add_field('chat_id', self.chat_id)
            data.add_field('document', file, filename=Path(file_path).name)
            if caption:
                data.add_field('caption', caption)

            connector = aiohttp.TCPConnector(ssl=_ssl_context())
            async with aiohttp.ClientSession(connector=connector) as session:
                async with session.post(url, data=data) as response:
                    if response.status != 200:
                        error = await response.text()
                        raise Exception(f"Błąd wysyłania dokumentu: {error}")
                    return await response.json()

    async def send_offer_for_approval(
        self,
        html_path: str,
        top_count: int,
        total_count: int,
        search_query: str = "",
        auction_window_hours: Optional[int] = None,
    ) -> None:
        """
        Wysyła ofertę HTML do zatwierdzenia.
        Oczekuje na /approve lub /reject (nasłuchiwanie przez wait_for_approval).
        """
        window_str = f"{auction_window_hours}h" if auction_window_hours else "bez limitu"
        text = (
            f"🚗 *Nowa oferta do zatwierdzenia*\n\n"
            f"📋 Zapytanie: {search_query or 'brak opisu'}\n"
            f"⏱ Okno aukcji: {window_str}\n"
            f"⭐ TOP rekomendacji: *{top_count}*\n"
            f"📊 Wszystkich propozycji: *{total_count}*\n\n"
            f"Otwórz załączony plik HTML w przeglądarce, aby zobaczyć pełną ofertę.\n\n"
            f"Odpowiedz:\n"
            f"✅ `/approve` — zatwierdź i wyślij email\n"
            f"❌ `/reject` — odrzuć"
        )
        await self.send_message(text, parse_mode="Markdown")
        await self.send_document(html_path, caption="📄 Oferta HTML — otwórz w przeglądarce")

    async def send_report_for_approval(self, report_path: str, lot_count: int, top_count: int):
        text = (
            f"Nowy raport wyszukiwania aut\n\n"
            f"Znaleziono: {lot_count} lotow\n"
            f"TOP rekomendacje: {top_count}\n\n"
            f"Raport gotowy do wysłania. Wybierz akcję:"
        )

        keyboard = {
            "inline_keyboard": [
                [
                    {"text": "Zatwierdź i wyślij", "callback_data": "approve"},
                    {"text": "Odrzuć", "callback_data": "reject"}
                ]
            ]
        }

        await self.send_message(text, reply_markup=keyboard)
        await self.send_document(report_path, caption=f"Raport DOCX ({lot_count} lotów, TOP {top_count})")
        self.pending_approval = True

    async def wait_for_approval(self, timeout: int = 1800) -> Optional[str]:
        result = await self._listen_for_callback(timeout)
        self.pending_approval = False
        return result

    async def _listen_for_callback(self, timeout: int) -> Optional[str]:
        import aiohttp
        import time

        url = f"{self.base_url}/getUpdates"
        start_time = time.time()
        last_update_id = 0

        while time.time() - start_time < timeout:
            try:
                connector = aiohttp.TCPConnector(ssl=_ssl_context())
                async with aiohttp.ClientSession(connector=connector) as session:
                    params = {"offset": last_update_id + 1, "timeout": 30}
                    async with session.get(url, params=params) as response:
                        if response.status != 200:
                            await asyncio.sleep(1)
                            continue

                        data = await response.json()
                        if not data.get("ok"):
                            await asyncio.sleep(1)
                            continue

                        for update in data.get("result", []):
                            last_update_id = update["update_id"]

                            # Obsługa inline keyboard callback
                            if "callback_query" in update:
                                callback = update["callback_query"]
                                callback_data = callback.get("data")
                                await self._answer_callback_query(callback["id"])
                                if callback_data in ["approve", "reject"]:
                                    return callback_data

                            # Obsługa komend tekstowych /approve i /reject
                            if "message" in update:
                                msg = update["message"]
                                text = msg.get("text", "").strip().lower()
                                if text in ["/approve", "/reject"]:
                                    action = text.lstrip("/")
                                    ack = "✅ Zatwierdzono! Wysyłam email..." if action == "approve" else "❌ Odrzucono."
                                    try:
                                        await self.send_message(ack)
                                    except Exception:
                                        pass
                                    return action
            except Exception as e:
                print(f"[Telegram] Błąd nasłuchiwania: {e}")
                await asyncio.sleep(1)

        return None

    async def _answer_callback_query(self, callback_query_id: str):
        import aiohttp

        url = f"{self.base_url}/answerCallbackQuery"
        connector = aiohttp.TCPConnector(ssl=_ssl_context())
        async with aiohttp.ClientSession(connector=connector) as session:
            await session.post(url, json={"callback_query_id": callback_query_id})

    async def send_error_notification(self, error_message: str):
        import html
        await self.send_message(f"Błąd w systemie automatyzacji\n\n{html.escape(error_message)}")

    async def send_success_notification(self, message: str):
        await self.send_message(f"Sukces\n\n{message}")
