# Odbudowa serwera od zera

Spisane 10 października 2026, po tym jak dystrybucja WSL zniknęła razem z całym
dyskiem i okazało się, że repo nie zawierało wszystkiego, co potrzebne do
powrotu. Ten plik ma sprawić, że następnym razem to będzie procedura, a nie
śledztwo.

## Co trzyma ten serwer i czego nie ma w gicie

| Rzecz | Gdzie była | W repo? |
| --- | --- | --- |
| `usacar-api.service` | `/etc/systemd/system/` | **teraz tak** (`infra/`) — wcześniej nie |
| `usacar-dashboard.service` | `/etc/systemd/system/` | tak |
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
sytuację wyłącznie kopia ściągnięta wcześniej na Maca. README backupu ostrzegał
przed tym wprost i ostrzeżenie okazało się trafne, więc: `scp -r
wsl2-cf:/home/dawid/backups/<data> .` raz na jakiś czas, zanim będzie potrzebne.

## Podział pracy

Część windowsową musi zrobić człowiek przy maszynie. Resztę da się zrobić zdalnie
po SSH, więc warto postawić `openssh-server` jak najwcześniej i oddać robotę.

### 1. Windows (przy maszynie)

```powershell
wsl --install -d Ubuntu          # po restarcie poprosi o nazwę użytkownika: dawid
```

Potem, w świeżym Ubuntu, minimum potrzebne do przejęcia zdalnie:

```bash
sudo apt update && sudo apt install -y openssh-server
sudo sed -i 's/^#\?Port .*/Port 22/' /etc/ssh/sshd_config
sudo systemctl enable --now ssh
ip -4 addr show eth0 | grep -oP 'inet \K[\d.]+'   # adres WSL, potrzebny niżej
```

Przekierowanie z sieci lokalnej na WSL (w **cmd jako administrator**, podstaw
adres z poprzedniej komendy):

```cmd
netsh interface portproxy add v4tov4 listenaddress=0.0.0.0 listenport=2222 connectaddress=<ADRES_WSL> connectport=22
netsh advfirewall firewall add rule name="usacar-ssh" dir=in action=allow protocol=TCP localport=2222
```

Od tego momentu reszta idzie zdalnie: `ssh -p 2222 dawid@192.168.0.197`.

### 2. Zanim WSL zacznie gasnąć

Te trzy rzeczy kosztowały noc 18 sierpnia. WSL2 wygasza maszynę wirtualną, gdy
nie ma do niej żadnego klienta, a procesy w środku tego nie powstrzymują:
panel wstawał, oddawał 200 i po kilkunastu minutach znikał.

`%UserProfile%\.wslconfig`:

```ini
[wsl2]
vmIdleTimeout=-1
```

Skrót w Autostarcie (`shell:startup`), plik `usacar-wsl.vbs`:

```vbs
Set powloka = CreateObject("WScript.Shell")
powloka.Run "wsl.exe -d Ubuntu -u root --exec /usr/bin/sleep infinity", 0, False
```

Autologowanie konta bez hasła — rejestrem, nie przez `netplwiz` (tamto okno chce
zapisać hasło, a przy pustym nie ma czego). W cmd jako administrator:

```cmd
reg add "HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon" /v AutoAdminLogon /t REG_SZ /d 1 /f
reg add "HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon" /v DefaultUserName /t REG_SZ /d Dawid /f
```

`DefaultPassword` ma NIE istnieć — przy pustym haśle jego brak jest poprawną
wartością.

### 3. Reszta: `infra/odbudowa.sh`

Skrypt stawia pakiety, Dockera z Postgresem, oba repozytoria, środowisko Pythona,
Playwrighta, odtwarza konfigurację i dane z kopii, instaluje jednostki systemd
i włącza je. Jest idempotentny, więc można go puścić ponownie po poprawce.

## Czego skrypt NIE zrobi za Ciebie

1. **Tunel Cloudflare.** Poświadczenia przepadły. `cloudflared tunnel login`
   otwiera przeglądarkę, potem `cloudflared tunnel token 99e0969c-9300-4a2e-a857-c54ff1b7273e`
   albo nowy tunel i przepięcie DNS. Do tego czasu panel działa wyłącznie z LAN.
2. **Logowanie Claude Code.** `claude /login` jako użytkownik `dawid` — ścieżka
   produkcyjna analizy i raportów chodzi na subskrypcji, nie na kluczu API.
3. **Sesje giełd.** Copart, IAAI i Manheim trzeba zalogować od nowa; profil
   Chrome z kopii bywa po dwóch miesiącach nieważny.
4. **Hasło do panelu.** Jest w `dashboard.env` z kopii. Jeśli go nie pamiętasz,
   wygeneruj nowy hash scrypt i podmień.
