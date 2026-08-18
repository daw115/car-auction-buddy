"""Render obrazka wołany tak, jak woła go serwer: z wnętrza pętli asyncio.

Synchroniczne API Playwrighta odmawia pracy, gdy w bieżącym wątku kręci się
pętla zdarzeń. Wywołane wprost z Pythona to samo wywołanie przechodzi, więc błąd
pokazał się dopiero na żywym serwerze jako 503. Ten test pilnuje, żeby wersja dla
endpointu naprawdę schodziła z pętli, a nie tylko nazywała się „async".
"""

import asyncio
import threading

from report import screenshot


def test_wersja_dla_endpointu_renderuje_poza_watkiem_petli(monkeypatch) -> None:
    watki: list[int] = []

    def udawany_render(html, *, szerokosc=None):
        watki.append(threading.get_ident())
        return b"PNG"

    monkeypatch.setattr(screenshot, "html_na_png", udawany_render)

    async def z_petli():
        watki.append(threading.get_ident())  # wątek pętli
        return await screenshot.html_na_png_async("<html></html>")

    wynik = asyncio.run(z_petli())

    assert wynik == b"PNG"
    watek_petli, watek_renderu = watki
    assert watek_renderu != watek_petli, "render poszedł w wątku pętli — Playwright to odrzuci"
