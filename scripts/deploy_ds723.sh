#!/usr/bin/env bash
# scripts/deploy_ds723.sh
#
# Skrypt deploymentu na DS723+ (100.87.84.118)
# Uruchamiaj z Mac mini: bash scripts/deploy_ds723.sh
#
# Wymagania:
#   - SSH dostęp do DS723+ (klucz lub hasło)
#   - Docker zainstalowany na DS723+ (Synology Container Manager)
#   - Repo sklonowane na DS723+ w /volume1/docker/ifg/program-do-faktur/
#   - Plik .env.production w /volume1/docker/ifg/ (NIE w repo)

set -euo pipefail

# ── Konfiguracja ──────────────────────────────────────────────
DS_HOST="100.87.84.118"
DS_USER="zdalny_admin"
DS_PORT="32122"
REMOTE_DIR="/volume1/homes/zdalny_admin/ifg/program-do-faktur"
COMPOSE_FILE="docker/docker-compose.prod.yml"
ENV_FILE="/volume1/homes/zdalny_admin/ifg/.env.production"

# ── Kolory ────────────────────────────────────────────────────
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()  { echo -e "${GREEN}[deploy]${NC} $*"; }
warn()  { echo -e "${YELLOW}[warn]${NC}  $*"; }
error() { echo -e "${RED}[error]${NC} $*"; exit 1; }

# ── Sprawdź czy jesteśmy na main i czy tree jest czyste ───────
BRANCH=$(git rev-parse --abbrev-ref HEAD)
[[ "$BRANCH" != "main" ]] && error "Deploy tylko z brancha main (jesteś na: $BRANCH)"

if [[ -n "$(git status --porcelain)" ]]; then
  warn "Masz niezatwierdzone zmiany. Commituj przed deployem."
  git status --short
  read -r -p "Kontynuować mimo to? [y/N] " ans
  [[ "$ans" =~ ^[Yy]$ ]] || exit 1
fi

COMMIT=$(git rev-parse --short HEAD)
info "Deploying commit: $COMMIT"

# ── Buduj frontend lokalnie na Mac mini ───────────────────────
info "Budowanie obrazu frontendu (lokalnie — Mac mini)..."
docker build -f docker/Dockerfile.frontend -t ifg-frontend:latest . \
  || error "Błąd budowania frontendu"

FRONTEND_TAR="/tmp/ifg-frontend-${COMMIT}.tar.gz"
info "Eksportuję obraz → $FRONTEND_TAR"
docker save ifg-frontend:latest | gzip > "$FRONTEND_TAR"

info "Przesyłam obraz na $DS_HOST (SCP)..."
scp -O -q -P "${DS_PORT}" "$FRONTEND_TAR" "${DS_USER}@${DS_HOST}:/tmp/ifg-frontend.tar.gz"
rm -f "$FRONTEND_TAR"
info "Obraz frontendu przesłany ✓"

# ── Wyślij na DS723+ przez SSH ────────────────────────────────
info "Łączę z $DS_USER@$DS_HOST..."

ssh -p "${DS_PORT}" "${DS_USER}@${DS_HOST}" bash <<REMOTE
set -euo pipefail

# Docker na Synology nie jest w domyślnym PATH
export PATH="/var/packages/ContainerManager/target/usr/bin:$PATH"

echo "→ Ładuję obraz frontendu"
docker load < /tmp/ifg-frontend.tar.gz
rm -f /tmp/ifg-frontend.tar.gz

echo "→ Przechodzę do $REMOTE_DIR"
cd "$REMOTE_DIR"

echo "→ git pull origin main"
git pull origin main

echo "→ Buduję obrazy Docker"
docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" build --no-cache

echo "→ Restartuję serwisy"
docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" up -d --remove-orphans

echo "→ Migracje bazy danych"
docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" exec -T api alembic upgrade head

echo "→ Status"
docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" ps
REMOTE

info "Deploy zakończony pomyślnie ✓  (commit: $COMMIT)"
info "API:      http://$DS_HOST:8000/health"
info "Frontend: http://$DS_HOST:3000"
