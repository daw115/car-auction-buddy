# Odbudowa serwera od zera

Spisane 10 października 2026, po tym jak dystrybucja WSL zniknęła razem z całym
dyskiem. **Przebieg został wykonany realnie** na świeżym Ubuntu 26.04 w WSL2 i
ten plik opisuje to, co się stało, nie to, co powinno zadziałać. Następny raz ma
być procedurą, nie śledztwem.

Czas przebiegu: około 40 minut, z czego trzy komendy po stronie Windowsa.

## Co trzyma ten serwer i czego nie ma w gicie

| Rzecz | Gdzie była | W repo? |
| --- | --- | --- |
| `usacar-api.service` + dropiny | `/etc/systemd/system/` | **teraz tak** (`infra/`) |
| `usacar-watchdog.{service,timer}`, `cloudflared.service` | `/etc/systemd/system/` | **teraz tak** (`infra/`) |
| `usacar-dashboard.service`, backup, skrypty wdrożeniowe | `/etc/systemd/system/`, `/usr/local/bin/` | tak, w repo **panelu** (`deploy/selfhost/`) |
| `usacar-watch.{service,timer}`, Manheim, Chrome CDP | `/etc/systemd/system/`, `~/.config/systemd/user/` | tak, w `usa-car-finder/scripts/` |
| Sekrety backendu | `~/usacar/usa-car-finder/.env` | nie, i nie powinno |
| Sekrety panelu | `/etc/usacar/dashboard.env` | nie |
| Sekrety bazy | `/opt/usacar-db/.env` | nie |
| Config tunelu | `/etc/cloudflared/config.yml` | nie |
| **Poświadczenia tunelu** | `/etc/cloudflared/<id>.json` | **nie i nie da się odtworzyć** |
| Bazy SQLite, raporty, Postgres | `~/usacar/.../data`, `~/backups` | nie |
| Sesje Copart / IAAI / Manheim | `playwright_profiles/`, profil Chrome | nie |

Wszystko poza poświadczeniami tunelu siedzi w nocnej kopii
(`usacar-backup.timer`, katalog `~/backups/<data>/`, plik `config.tar.zst`).

**Kopia leżała na tym samym dysku co dane i zginęła razem z nim.** Uratowała
sytuację wyłącznie kopia ściągnięta wcześniej na Maca — ze stanu sprzed dwóch
miesięcy, więc dwa miesiące leadów, spraw i raportów przepadły. Do tego kopia
powstawała jako `root:root 0700`, czyli użytkownik `dawid` nie mógł jej nawet
wylistować, mimo że README każe mu ją ściągać poza serwer. Naprawione w repo
panelu; ściągaj regularnie:

```bash
scp -r dawid@<serwer>:/home/dawid/backups/<data> .
```

## Podział pracy

Część windowsową musi zrobić człowiek przy maszynie. Resztę da się zrobić zdalnie
po SSH, więc warto postawić `openssh-server` jak najwcześniej i oddać robotę.

### 1. Windows (przy maszynie)

```powershell
wsl --install -d Ubuntu          # po restarcie poprosi o nazwę użytkownika: dawid
```

Ubuntu **nie startuje sam po restarcie Windowsa** — trzeba go raz otworzyć
(menu Start → `Ubuntu`, albo `wsl -d Ubuntu`). Zamknięcie okna gasi całą maszynę
wirtualną, dopóki nie wejdzie w życie autostart z punktu 2.

Potem, w świeżym Ubuntu, minimum potrzebne do przejęcia zdalnie:

```bash
sudo apt update && sudo apt install -y openssh-server
sudo systemctl enable --now ssh
ip -4 addr show eth0 | grep -oP 'inet \K[\d.]+'   # adres WSL, potrzebny niżej
```

Przekierowanie z sieci lokalnej na WSL (w **cmd jako administrator**, podstaw
adres z poprzedniej komendy). `netsh` to program Windows — wklejony w Ubuntu
odpowie `command not found`, a bez podniesionych uprawnień odmówi dostępu:

```cmd
netsh interface portproxy add v4tov4 listenaddress=0.0.0.0 listenport=2222 connectaddress=<ADRES_WSL> connectport=22
netsh advfirewall firewall add rule name="usacar-ssh" dir=in action=allow protocol=TCP localport=2222
```

**Ten adres zmienia się po każdym restarcie Windowsa**, więc przekierowanie samo
się rozsypuje i SSH przestaje działać bez żadnego komunikatu. Na stałe załatwia
to zadanie w Harmonogramie, odnawiające wpis przy logowaniu (w cmd jako
administrator, jednorazowo):

```cmd
schtasks /create /tn "usacar-portproxy" /sc onlogon /rl highest /f /tr "cmd /c for /f \"tokens=*\" %%i in ('wsl -d Ubuntu -- ip -4 -o addr show eth0 ^| awk '{print $4}' ^| cut -d/ -f1') do netsh interface portproxy set v4tov4 listenaddress=0.0.0.0 listenport=2222 connectaddress=%%i connectport=22"
```

Od tego momentu reszta idzie zdalnie: `ssh -p 2222 dawid@192.168.0.197`.

Zdalne kroki wymagają `sudo` bez hasła, bo każda komenda leci nową sesją SSH i
zapamiętane hasło z konsoli nie przechodzi. Skrypty wdrożeniowe i tak wołają
`sudo -n systemctl restart`, więc stary serwer musiał mieć to samo:

```bash
echo "dawid ALL=(ALL) NOPASSWD:ALL" | sudo tee /etc/sudoers.d/dawid-nopasswd
sudo chmod 440 /etc/sudoers.d/dawid-nopasswd
```

### 2. Zanim WSL zacznie gasnąć

Te trzy rzeczy kosztowały noc 18 sierpnia. WSL2 wygasza maszynę wirtualną, gdy
nie ma do niej żadnego **klienta**, a procesy w środku tego nie powstrzymują:
panel wstawał, oddawał 200 i po kilkunastu minutach znikał.

`C:\Users\<użytkownik>\.wslconfig`:

```ini
[wsl2]
vmIdleTimeout=-1
```

Skrót w Autostarcie (`shell:startup`), plik `usacar-wsl.vbs`:

```vbs
Set powloka = CreateObject("WScript.Shell")
powloka.Run "wsl.exe -d Ubuntu --exec /usr/bin/sleep infinity", 0, False
```

Autologowanie konta bez hasła — rejestrem, nie przez `netplwiz` (tamto okno chce
zapisać hasło, a przy pustym nie ma czego). W cmd jako administrator; podstaw
nazwę konta Windows, która na tej maszynie brzmi `User`, nie `Dawid`:

```cmd
reg add "HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon" /v AutoAdminLogon /t REG_SZ /d 1 /f
reg add "HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon" /v DefaultUserName /t REG_SZ /d User /f
```

`DefaultPassword` ma NIE istnieć — przy pustym haśle jego brak jest poprawną
wartością. Po wyczyszczeniu dysku te wpisy znikają, więc sprawdź je wprost:
`reg query ... /v AutoAdminLogon`.

### 3. Reszta: `infra/odbudowa.sh`

```bash
./odbudowa.sh /home/dawid/backups/2026-08-10-0116
```

Jedenaście kroków: pakiety, Chrome i cloudflared, oba repozytoria, Python,
chromium, sekrety, dane, Postgres, bun, jednostki systemd, wdrożenia przez
skrypty produkcyjne plus weryfikacja po HTTP. Idempotentny.

## Co ten przebieg wywrócił

Kolejność i obejścia w skrypcie nie są ozdobne. Każde wynikło z błędu.

- **Ubuntu 26.04 ma w apt wyłącznie Pythona 3.14**, a `python3.11/12/13` nie są
  dostępne żadną drogą. Przypięte zależności są z epoki 3.11: `pydantic 2.7.1` i
  `lxml 5.2.2` nie mają paczek dla 3.14 i kompilowałyby się ze źródeł, a
  `playwright 1.44.0` ma w sobie sterownik, który o 3.14 nie wie. Przypinamy
  **Pythona** (`uv python install 3.12`), nie ruszamy kilkudziesięciu bibliotek
  działającego wydania.
- **`uv venv` nie wkłada do środowiska `pip`.** Pierwsza instalacja zależności
  poleciała przez `python -m pip install -r requirements.txt`, wypisała
  `No module named pip` i **wyszła z kodem 0** — bo komunikat przeszedł przez
  `tail`. Środowisko było puste, a wyglądało na gotowe. Dokładnie ten wzorzec,
  który opisuje `CLAUDE.md`: cicha porażka udająca mały wynik.
- **`playwright install --with-deps` nie przejdzie.** Lista zależności w 1.44.0
  zna `libasound2`, które w 26.04 nazywa się `libasound2t64`; apt odmawia,
  playwright przerywa i kończy na `Failed to install browsers`. Google Chrome z
  kroku 2 ciągnie te biblioteki, więc chromium wystarczy *pobrać*.
- **Instalator buna milczy o `unzip`** do chwili, gdy go nie znajdzie. CPU tego
  serwera (i5-3210M) nie ma AVX2 — potwierdzone — więc standardowy bun kończy
  SIGILL-em; wariant `bun-v1.2.14` dobiera baseline i odpowiada.
- **Skrypty wdrożeniowe żyją w repo panelu**, nie backendu (`deploy/selfhost/`).
  Poprzednia wersja tego pliku szukała ich w `infra/` i nie znalazła.
- **Dropin z kopii przypinał martwy release.** `90-kiro-release-caf6b6e.conf`
  miał w `ExecStart` ścieżkę `/opt/usacar/releases/ebf176d-caf6b6e596ec/...`,
  której po odbudowie nie ma. Gorzej: `usacar-deploy-api.sh` przestawia symlink
  `current` i restartuje usługę, więc na starym serwerze **każde wdrożenie
  backendu restartowało proces chodzący dalej na starym kodzie**. Zastąpione
  przez `20-release.conf` wskazujący `/opt/usacar/current/usa-car-finder`.
- **Dwa różne skrypty nazywają się `usacar-watchdog.sh`** i celują w ten sam
  plik w `/usr/local/bin`. Ten z repo panelu pilnuje backendu **i** panelu, z
  osobnymi licznikami i świadomym wyborem `/api/version` zamiast `/api/health`;
  ten z backendu zna tylko API. Instalować nowszy — kolejność decyduje.
- **`BIDFAX_CHROME_CDP_URL` wskazywał adres bramy starego WSL** (`172.29.176.1`),
  który po odbudowie jest inny. Enrichment milczałby. Przestawione na
  `127.0.0.1:9222`, czyli na `ahb-cdp-chrome.service` — ten adres nie zależy od
  tego, jaką sieć WSL sobie wylosuje.
- **`KIRO_CLI_PATH` prowadzi w pustkę.** Kopia `.env` jest z czasów, gdy analiza
  stała na Kiro, a binarka żyła tylko na skasowanym dysku. Wydanie 1.0.0 chodzi
  na Claude Code (`AI_ANALYSIS_MODE=claude-code`), instalowanym natywnie do
  `~/.local/bin/claude` — `ai/claude_code.cli_path()` szuka właśnie tam, bo samo
  `claude` nie jest widoczne spod usługi systemd.
- **Repozytorium jest publiczne**, więc klon nie wymaga żadnych poświadczeń.
  Uwaga na gałęzie: backend to `feat/claude-code-provider`, panel
  `feat/selfhost`, a `main` jest z 20 lipca i nie zna całego sierpnia.

## Czego skrypt NIE zrobi za Ciebie

1. **Tunel Cloudflare.** Poświadczenia przepadły z dyskiem.
   `cloudflared tunnel login` otwiera przeglądarkę, potem
   `cloudflared tunnel token --cred-file /etc/cloudflared/<id>.json <id>`
   i `sudo systemctl enable --now cloudflared`. Do tego czasu panel działa
   wyłącznie z LAN.
2. **Logowanie Claude Code.** `claude /login` jako `dawid`. Bez tego analiza i
   raporty kończą się jasnym błędem („Claude Code niezalogowany"), nie ciszą.
3. **Sesje giełd.** Copart, IAAI i Manheim trzeba zalogować od nowa; profile z
   kopii bywają po dwóch miesiącach nieważne.
4. **Cloudflare na Bidfaxie.** Raz przejść zabezpieczenie w przeglądarce
   podłączonej do `127.0.0.1:9222`.
5. **Hasło do panelu.** Hash jest w Postgresie (`site_user_passwords`) i wraca ze
   zrzutu. Jeśli go nie pamiętasz, wygeneruj nowy scrypt i podmień.

## Weryfikacja, że serwer naprawdę stoi

Zielone testy nie znaczą, że działa. Sprawdzaj drogą produkcyjną:

```bash
curl -s localhost:8000/version          # backend przez usługę, nie przez python -m
curl -s localhost:3000/api/version      # panel, commit musi zgadzać się z wdrażanym
curl -s -o /dev/null -w '%{http_code}\n' localhost:3001/rest/v1/   # baza przez Caddy
systemctl is-active usacar-api usacar-dashboard docker cloudflared
systemctl list-timers --all | grep usacar
sudo systemctl start usacar-backup.service && ls -ld ~/backups/*/
sudo systemctl stop usacar-dashboard && sudo /usr/local/bin/usacar-watchdog.sh   # ×2, ma podnieść
```
