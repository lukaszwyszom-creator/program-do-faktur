# Migracja projektu na Mac mini — kompletny plan

> Projekt: **ksef-backend** (Python 3.13 / FastAPI / PostgreSQL 17 / Docker Compose)
> Model pracy: **VS Code Remote SSH** z PC → Mac mini
> Data przygotowania: 2026-04-14

---

## 1. Docelowa struktura katalogów na Mac mini

```
~/dev/
└── program-do-faktur/          ← sklonowane repo (jedyne źródło prawdy)
    ├── .venv/                  ← virtualenv (poza repo, w .gitignore)
    ├── .env                    ← sekrety lokalne (poza repo, w .gitignore)
    ├── app/
    ├── alembic/
    ├── docker/
    ├── frontend-react/
    ├── tests/
    ├── pyproject.toml
    └── docker-compose.yml      → docker/docker-compose.yml
```

**Przyczyna** → repo na lokalnym SSD Mac mini, nie na udziale sieciowym
**Skutek** → brak latencji I/O, brak problemów z file-locking, natywna wydajność Git
**Działanie** → `~/dev/` jako katalog roboczy, `.venv` wewnątrz projektu (wygodne dla VS Code)

---

## 2. Przygotowanie Mac mini — komendy krok po kroku

### 2.1. Xcode CLI Tools + Git + Homebrew

```bash
# Xcode CLI (zawiera Git)
xcode-select --install

# Sprawdź Git
git --version
# → git version 2.x.x (Apple Git)

# Homebrew (menedżer pakietów)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Dodaj brew do PATH (Apple Silicon — M1/M2/M3/M4)
echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile
eval "$(/opt/homebrew/bin/brew shellenv)"
```

**Przyczyna** → macOS nie ma Homebrew domyślnie, a Git z Xcode jest stary
**Skutek** → bez Homebrew nie zainstalujemy Python 3.13 ani zależności WeasyPrint
**Działanie** → Homebrew jako jedyne źródło pakietów systemowych

### 2.2. Python 3.13

```bash
# Zainstaluj Python 3.13
brew install python@3.13

# Sprawdź
python3.13 --version
# → Python 3.13.x

# Ustaw jako domyślny (opcjonalnie)
echo 'alias python=python3.13' >> ~/.zprofile
echo 'alias pip="python3.13 -m pip"' >> ~/.zprofile
source ~/.zprofile
```

**Przyczyna** → projekt wymaga `requires-python = ">=3.13"`
**Skutek** → macOS ma wbudowany Python 3.9–3.12 (zależnie od wersji), za stary
**Działanie** → `brew install python@3.13` daje izolowaną, aktualną wersję

### 2.3. Zależności systemowe WeasyPrint

```bash
# WeasyPrint wymaga Cairo, Pango, GDK-Pixbuf, Fontconfig
brew install cairo pango gdk-pixbuf libffi fontconfig
```

**Przyczyna** → `weasyprint>=63.0` w pyproject.toml wymaga bibliotek C (Cairo, Pango)
**Skutek** → `pip install weasyprint` zakończy się błędem linkera bez tych bibliotek
**Działanie** → zainstaluj PRZED `pip install`

### 2.4. Docker Desktop (dla PostgreSQL i kontenerów)

```bash
# Zainstaluj Docker Desktop for Mac
brew install --cask docker

# Uruchom Docker Desktop raz ręcznie → Settings → Start Docker Desktop when you log in
open -a Docker
```

**Przyczyna** → projekt używa PostgreSQL 17 w Docker Compose
**Skutek** → bez Dockera nie uruchomisz bazy danych
**Działanie** → Docker Desktop z autostartem; Linux silnik działa natywnie na ARM

### 2.5. Klonowanie repo + virtualenv + zależności

```bash
# Katalog roboczy
mkdir -p ~/dev && cd ~/dev

# Klonuj repo
git clone git@github.com:lukaszwyszom-creator/program-do-faktur.git
cd program-do-faktur

# Utwórz virtualenv
python3.13 -m venv .venv

# Aktywuj
source .venv/bin/activate

# Uaktualnij pip
pip install --upgrade pip setuptools wheel

# Zainstaluj projekt z zależnościami
pip install --no-build-isolation -e .

# Zainstaluj zależności dev (testy)
pip install pytest httpx

# Sprawdź
python -c "import fastapi; print(fastapi.__version__)"
```

**Przyczyna** → `.venv` wewnątrz projektu to konwencja rozpoznawana przez VS Code
**Skutek** → VS Code Remote SSH automatycznie wykryje interpreter i aktywuje venv
**Działanie** → `-e .` (editable install) — zmiany w kodzie widoczne bez reinstalacji

### 2.6. Konfiguracja .env + uruchomienie

```bash
# Skopiuj szablon
cp .env.example .env

# Edytuj — ustaw lokalne wartości
# UWAGA: przy pracy bez Dockera zmień hostname bazy z "db" na "localhost"
nano .env
```

Kluczowe zmiany w `.env` dla pracy lokalnej (bez Docker Compose):
```env
DATABASE_URL=postgresql+psycopg://postgres:twoje_haslo@localhost:5432/ksef_backend
JWT_SECRET_KEY=<wygeneruj: python -c "import secrets; print(secrets.token_hex(32))">
INITIAL_ADMIN_PASSWORD=<silne hasło>
```

Uruchomienie:
```bash
# Opcja A: cały stack przez Docker Compose
cd docker && docker compose up -d && cd ..

# Opcja B: tylko baza w Dockerze, app nativnie (lepsze do developmentu)
docker run -d --name ksef-db \
  -e POSTGRES_DB=ksef_backend \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=twoje_haslo \
  -p 5432:5432 \
  postgres:17

# Poczekaj na gotowość bazy
until docker exec ksef-db pg_isready; do sleep 1; done

# Migracje Alembic
alembic upgrade head

# Uruchom API
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# W osobnym terminalu: worker
python -m app.worker
```

**Przyczyna** → Opcja B (baza w Dockerze + app natywnie) daje hot-reload i łatwiejszy debugging
**Skutek** → VS Code Remote SSH mogą attachować debugger do natywnego procesu, nie do kontenera
**Działanie** → `--host 0.0.0.0` pozwala na dostęp z PC przez forwarded port

---

## 3. Konfiguracja SSH na Mac mini

### 3.1. Włącz serwer SSH

```bash
# Włącz Remote Login (wymaga hasła administratora macOS)
sudo systemsetup -setremotelogin on

# Sprawdź status
sudo systemsetup -getremotelogin
# → Remote Login: On

# Sprawdź, że sshd nasłuchuje
sudo lsof -i :22
```

**Przyczyna** → macOS ma wbudowany sshd, ale jest domyślnie wyłączony
**Skutek** → VS Code Remote SSH nie połączy się bez działającego sshd
**Działanie** → jeden raz `setremotelogin on`, przetrwa restarty

### 3.2. Klucz SSH z PC → Mac mini (bezhasłowy dostęp)

Na **PC (Windows)**:
```powershell
# Wygeneruj klucz (jeśli nie masz)
ssh-keygen -t ed25519 -C "pc-do-macmini"

# Skopiuj klucz publiczny na Mac mini
type $env:USERPROFILE\.ssh\id_ed25519.pub | ssh uzytkownik@IP_MAC_MINI "mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"

# Sprawdź
ssh uzytkownik@IP_MAC_MINI "echo OK"
```

**Przyczyna** → VS Code Remote SSH odpytuje o hasło przy każdej operacji (otwarcie, terminal, debug)
**Skutek** → bez klucza będziesz wpisywać hasło dziesiątki razy dziennie
**Działanie** → klucz ed25519 + `authorized_keys` = bezhasłowe połączenia

### 3.3. Konfiguracja sshd na Mac mini (opcjonalne ulepszenia)

```bash
# /etc/ssh/sshd_config — dodaj/zmień:
sudo nano /etc/ssh/sshd_config
```

```
# Keepalive — zapobiega timeoutom VS Code
ClientAliveInterval 60
ClientAliveCountMax 3

# Szybsze logowanie (wyłącz DNS reverse lookup)
UseDNS no
```

```bash
# Restart sshd po zmianach
sudo launchctl kickstart -k system/com.openssh.sshd
```

**Przyczyna** → VS Code Remote SSH trzyma otwartą sesję SSH godzinami
**Skutek** → bez keepalive router/NAT zamknie połączenie po ~5min nieaktywności
**Działanie** → `ClientAliveInterval 60` wysyła ping co minutę

### 3.4. Tailscale (jeśli praca spoza LAN)

```bash
# Jeśli Mac mini ma być dostępny z zewnątrz (znasz Tailscale z NAS-ów)
brew install --cask tailscale
# Zaloguj się → Mac mini dostanie adres 100.x.x.x
```

**Przyczyna** → PC i Mac mini mogą być w różnych sieciach
**Skutek** → bez VPN/Tailscale SSH nie przejdzie przez NAT
**Działanie** → Tailscale = zero-config WireGuard mesh; używaj adresu Tailscale w VS Code

---

## 4. Konfiguracja VS Code na PC

### 4.1. Rozszerzenie Remote SSH

```
Zainstaluj: ms-vscode-remote.remote-ssh
(w VS Code: Ctrl+Shift+X → szukaj "Remote - SSH" → Install)
```

### 4.2. Konfiguracja SSH hosta

Edytuj `~/.ssh/config` na PC (`$env:USERPROFILE\.ssh\config`):

```
Host macmini
    HostName IP_LUB_TAILSCALE_MAC_MINI
    User twoj_user_na_macu
    IdentityFile ~/.ssh/id_ed25519
    ServerAliveInterval 60
    ServerAliveCountMax 3
    ForwardAgent yes
```

**Przyczyna** → `Host macmini` to alias — nie musisz pamiętać IP
**Skutek** → VS Code pokaże "macmini" na liście hostów w Remote Explorer
**Działanie** → `ServerAliveInterval` z obu stron (klient+serwer) = stabilne połączenie

### 4.3. Otwarcie repo z Mac mini

1. `Ctrl+Shift+P` → `Remote-SSH: Connect to Host…` → wybierz `macmini`
2. Poczekaj na instalację VS Code Server na Mac mini (~30s za pierwszym razem)
3. `File → Open Folder` → `/Users/twoj_user/dev/program-do-faktur`
4. VS Code automatycznie wykryje `.venv` i zaproponuje jako interpreter Pythona

### 4.4. Zalecane rozszerzenia (zainstaluj w kontekście Remote)

Po połączeniu VS Code pokaże, że rozszerzenia trzeba zainstalować "on SSH: macmini":

| Rozszerzenie | Cel |
|---|---|
| `ms-python.python` | Interpreter, linting, debugging |
| `ms-python.vscode-pylance` | IntelliSense, type checking |
| `charliermarsh.ruff` | Szybki linter/formatter |
| `ms-azuretools.vscode-docker` | Docker Compose management |
| `mtxr.sqltools` + `mtxr.sqltools-driver-pg` | Podgląd bazy PostgreSQL |

### 4.5. Port forwarding (automatyczny)

VS Code Remote SSH automatycznie forwarduje porty. Gdy uruchomisz `uvicorn` na Mac mini na porcie 8000, VS Code pokaże powiadomienie i otworzy `http://localhost:8000` w przeglądarce PC.

Jeśli nie — ręcznie:
- `Ctrl+Shift+P` → `Forward a Port` → `8000`

---

## 5. Git — komendy operacyjne

### 5.1. Klonowanie (jednorazowo)

```bash
# SSH (rekomendowane — działa z kluczem)
git clone git@github.com:lukaszwyszom-creator/program-do-faktur.git ~/dev/program-do-faktur

# Lub HTTPS (wymaga token/credential helper)
git clone https://github.com/lukaszwyszom-creator/program-do-faktur.git ~/dev/program-do-faktur
```

### 5.2. Konfiguracja Git na Mac mini

```bash
cd ~/dev/program-do-faktur

git config user.name "Łukasz Wyszomirski"
git config user.email "twoj@email.com"

# Credential helper macOS Keychain (dla HTTPS)
git config --global credential.helper osxkeychain

# Albo klucz SSH do GitHub (zalecane)
ssh-keygen -t ed25519 -C "macmini-github"
cat ~/.ssh/id_ed25519.pub
# → dodaj w GitHub → Settings → SSH Keys
```

### 5.3. Codzienna praca

```bash
# Status
git status

# Pull (przed rozpoczęciem pracy)
git pull origin main

# Commit + push
git add -A
git commit -m "opis zmian"
git push origin main

# Log
git log --oneline -10
```

**Przyczyna** → Git SSH forwarding (`ForwardAgent yes` w config PC)
**Skutek** → `git push` z terminala VS Code Remote SSH używa klucza SSH z PC
**Działanie** → nie musisz kopiować klucza GitHub na Mac mini (opcjonalnie)

---

## 6. Backup repo z Mac mini na NAS

### Model: push-based cron z Mac mini → NAS (rsync over SSH)

```
Mac mini (źródło)  ──rsync/SSH──►  DS723+ (backup)
~/dev/program-do-faktur            /volume2/Dane/backup/program-do-faktur
```

### 6.1. Konfiguracja na Mac mini

```bash
# Klucz SSH Mac mini → NAS DS723+ (jednorazowo)
ssh-keygen -t ed25519 -C "macmini-nas-backup" -f ~/.ssh/id_nas_backup
ssh-copy-id -i ~/.ssh/id_nas_backup -p 32122 zdalny_admin@100.87.84.118

# Testuj
ssh -i ~/.ssh/id_nas_backup -p 32122 zdalny_admin@100.87.84.118 "echo OK"
```

### 6.2. Skrypt backupu

```bash
cat > ~/dev/backup_repo.sh << 'EOF'
#!/bin/bash
set -euo pipefail

REPO_DIR="$HOME/dev/program-do-faktur"
NAS_HOST="zdalny_admin@100.87.84.118"
NAS_PORT="32122"
NAS_DEST="/volume2/Dane/backup/program-do-faktur"
SSH_KEY="$HOME/.ssh/id_nas_backup"
LOG="$HOME/dev/backup_repo.log"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Backup start" >> "$LOG"

rsync -az --delete \
  --exclude '.venv/' \
  --exclude '__pycache__/' \
  --exclude 'node_modules/' \
  --exclude '.env' \
  --exclude 'postgres_data/' \
  -e "ssh -i $SSH_KEY -p $NAS_PORT -o ConnectTimeout=10" \
  "$REPO_DIR/" \
  "$NAS_HOST:$NAS_DEST/"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Backup OK" >> "$LOG"
EOF

chmod +x ~/dev/backup_repo.sh
```

### 6.3. Automatyczny backup (cron, co 6h)

```bash
# Edytuj crontab
crontab -e

# Dodaj linię:
0 */6 * * * $HOME/dev/backup_repo.sh 2>&1 | tail -1 >> $HOME/dev/backup_repo.log
```

### 6.4. Alternatywa: Git bare repo na NAS

```bash
# Na NAS (przez SSH)
ssh -p 32122 zdalny_admin@100.87.84.118
mkdir -p /volume2/Dane/backup/program-do-faktur.git
cd /volume2/Dane/backup/program-do-faktur.git
git init --bare

# Na Mac mini — dodaj NAS jako remote
cd ~/dev/program-do-faktur
git remote add nas ssh://zdalny_admin@100.87.84.118:32122/volume2/Dane/backup/program-do-faktur.git

# Push na NAS (ręcznie lub w hook)
git push nas main
```

**Przyczyna** → praca bezpośrednio na SMB = latencja I/O, file-locking, uszkodzenia `.git`
**Skutek** → repo na NAS tylko jako kopia, nigdy jako working directory
**Działanie** → `rsync --delete` lub `git push nas` = jednokierunkowy push

---

## 7. Stabilność środowiska zdalnego

### 7.1. Automatyczne uruchomienie usług po restarcie Mac mini

```bash
# Stwórz launchd plist dla PostgreSQL w Dockerze
cat > ~/Library/LaunchAgents/com.ksef.postgres.plist << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.ksef.postgres</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/local/bin/docker</string>
        <string>start</string>
        <string>ksef-db</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>StartInterval</key>
    <integer>30</integer>
</dict>
</plist>
EOF

launchctl load ~/Library/LaunchAgents/com.ksef.postgres.plist
```

Albo prościej — Docker Desktop "Start containers after restart" + `--restart always` na kontenerze.

### 7.2. Zapobieganie uśpieniu Mac mini

```bash
# Wyłącz usypianie (Mac mini bez monitora)
sudo pmset -a sleep 0
sudo pmset -a disksleep 0
sudo pmset -a displaysleep 0

# Sprawdź
pmset -g
```

**Przyczyna** → Mac mini poza ekranem usypia po 10min
**Skutek** → VS Code Remote SSH traci połączenie, procesy (uvicorn, docker) się zatrzymują
**Działanie** → `pmset sleep 0` = nigdy nie usypiaj; Mac mini jest serverem, nie laptopem

---

## 8. Typowe pułapki i obejścia

### Sieć / SSH

| Przyczyna | Skutek | Działanie |
|---|---|---|
| macOS firewall blokuje port 22 | VS Code Remote SSH timeout | System Settings → Network → Firewall → Options → Allow `sshd` |
| Router resetuje idle TCP po 5min | VS Code rozłącza się losowo | `ServerAliveInterval 60` po obu stronach (klient PC + serwer Mac) |
| Mac mini dostaje nowy IP po restarcie routera | SSH host unreachable | Ustaw static IP w routerze (DHCP reservation) lub użyj Tailscale |
| VS Code Server nie startuje (ARM) | "Could not establish connection" | Sprawdź `~/.vscode-server/` na Mac mini; usuń i połącz ponownie |

### Python / zależności

| Przyczyna | Skutek | Działanie |
|---|---|---|
| `pip install weasyprint` — brak Cairo | `OSError: cannot load library 'libgobject-2.0'` | `brew install cairo pango gdk-pixbuf` PRZED pip install |
| macOS SIP blokuje `lxml` compilation | `clang: error: linker command failed` | `brew install libxml2 libxslt` + `LDFLAGS="-L$(brew --prefix libxml2)/lib"` |
| `psycopg[binary]` nie ma wheel na ARM Mac | `pip install psycopg` build failure | `brew install libpq` + `pip install psycopg[c]` (kompiluje lokalnie) |
| `.venv` nie aktywuje się w VS Code | Pylance "import not resolved" | `Ctrl+Shift+P` → `Python: Select Interpreter` → `.venv/bin/python` |
| `python3` wskazuje na systemowy 3.9 | Błędy składni (walrus, `|` union types) | Zawsze używaj `python3.13` lub aktywuj `.venv` |

### Docker

| Przyczyna | Skutek | Działanie |
|---|---|---|
| Docker Desktop nie startuje po restarcie | `docker: command not found` | Docker Desktop → Settings → General → Start Docker Desktop when you log in |
| Port 5432 zajęty (macOS ma wbudowany postgres?) | `Bind for 0.0.0.0:5432 failed` | `lsof -i :5432` → `brew services stop postgresql` lub zmień port na 5433 |
| Apple Silicon = ARM; image `postgres:17` brak ARM | `exec format error` | Image `postgres:17` ma multi-arch (ARM64 OK). Jeśli nie: `--platform linux/amd64` |
| Docker zżera RAM (2GB default limit) | OOM killer, kontenery padają | Docker Desktop → Settings → Resources → Memory → min. 4GB |

### Git / praca zdalna

| Przyczyna | Skutek | Działanie |
|---|---|---|
| `ForwardAgent yes` a brak ssh-agent na PC | `git push` → `Permission denied (publickey)` | Na PC: `Get-Service ssh-agent \| Set-Service -StartupType Automatic; Start-Service ssh-agent; ssh-add` |
| `.env` wrzucony do repo | Sekrety publiczne | Upewnij się, że `.gitignore` zawiera `.env` (jest w projekcie — OK) |
| Praca na repo przez SMB mount z NAS | Corrupt `.git/index`, slow `git status` (30s+) | NIGDY nie otwieraj repo z NAS. Repo = lokalny SSD Mac mini |
| Konflikt CRLF (PC) vs LF (Mac) | Diff pokazuje zmianę każdej linii | `git config core.autocrlf input` na Mac mini |

### VS Code Remote SSH

| Przyczyna | Skutek | Działanie |
|---|---|---|
| Duże repo → VS Code indeksuje wolno | 100% CPU na Mac mini po połączeniu | `"files.watcherExclude": {"**/node_modules/**": true, "**/.venv/**": true}` |
| Rozszerzenia instalują się lokalnie (PC) zamiast Remote | IntelliSense nie działa | Kliknij "Install in SSH: macmini" przy każdym rozszerzeniu |
| Terminal VS Code używa zsh, a PATH nie ma brew | `python3.13: command not found` | Dodaj `eval "$(/opt/homebrew/bin/brew shellenv)"` do `~/.zprofile` (NIE `.bashrc`) |
| Otwarty port 8000 nie widoczny z PC | Przeglądarka `localhost:8000` — nic | VS Code auto-forward lub ręcznie: Ctrl+Shift+P → Forward a Port → 8000 |

---

## 9. Checklist — kolejność operacji

```
Mac mini:
  [ ] xcode-select --install
  [ ] zainstaluj Homebrew
  [ ] brew install python@3.13 cairo pango gdk-pixbuf fontconfig
  [ ] brew install --cask docker
  [ ] sudo systemsetup -setremotelogin on
  [ ] sudo pmset -a sleep 0
  [ ] (opcjonalnie) brew install --cask tailscale

PC (Windows):
  [ ] ssh-keygen -t ed25519 (jeśli nie masz)
  [ ] skopiuj klucz na Mac mini (authorized_keys)
  [ ] edytuj ~/.ssh/config — dodaj Host macmini
  [ ] VS Code: zainstaluj Remote - SSH
  [ ] VS Code: Connect to Host → macmini

Mac mini (przez VS Code Remote SSH):
  [ ] git clone repo do ~/dev/program-do-faktur
  [ ] python3.13 -m venv .venv
  [ ] source .venv/bin/activate
  [ ] pip install -e .
  [ ] cp .env.example .env → edytuj
  [ ] docker run postgres:17 (lub docker compose up)
  [ ] alembic upgrade head
  [ ] uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

Backup (po uruchomieniu):
  [ ] skonfiguruj klucz SSH Mac mini → NAS
  [ ] utwórz backup_repo.sh
  [ ] dodaj do crontab
```

---

## 10. Diagram przepływu

```
┌──────────┐   SSH (port 22)    ┌──────────────┐
│    PC    │ ─────────────────► │   Mac mini   │
│ Windows  │   VS Code Remote   │   ~/dev/     │
│          │ ◄───port forward── │   repo       │
└──────────┘   :8000 → :8000   │   .venv      │
                                │   Docker     │
                                │   ├ postgres │
                                │   └ (opcja)  │
                                └──────┬───────┘
                                       │ rsync/SSH (co 6h)
                                       ▼
                                ┌──────────────┐
                                │  NAS DS723+  │
                                │  /backup/    │
                                │  (kopia)     │
                                └──────────────┘
```
