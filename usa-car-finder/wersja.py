"""Numer wersji aplikacji — jedno miejsce dla całego backendu.

Wersję trzymamy w kodzie, nie w tagu gita: wdrożone wydanie żyje w katalogu
`/opt/usacar/releases/<sha>-<czas>` bez historii repozytorium, więc `git describe`
nie ma tam czego odczytać. Zapytany serwer musi umieć odpowiedzieć, czym jest,
bez zaglądania w symlinki.

1.0.0 to pierwsze wydanie ogłoszone jako gotowe do codziennej pracy brokera
(19 sierpnia 2026). Wcześniejsze „1.0.0" w konstruktorze FastAPI było wpisane
z ręki i nigdy nie zmieniane — nie znaczyło nic.
"""

WERSJA = "1.0.0"
NAZWA = "USA Car Finder"
