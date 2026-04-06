#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# smoke_test.sh — KSeF Backend pre-deploy smoke test
#
# Użycie:
#   BASE_URL=http://localhost:8000 bash scripts/smoke_test.sh
#
# Wymagania: curl, jq
# ---------------------------------------------------------------------------
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8000}"
ADMIN_USER="${ADMIN_USER:-admin}"
ADMIN_PASS="${ADMIN_PASS:-admin123!}"

PASS=0
FAIL=0
ERRORS=()

# ---------------------------------------------------------------------------
check() {
    local label="$1"
    local actual="$2"
    local expected="$3"
    if [[ "$actual" == *"$expected"* ]]; then
        echo "  PASS  $label"
        ((PASS++))
    else
        echo "  FAIL  $label  (got: $actual)"
        ERRORS+=("$label")
        ((FAIL++))
    fi
}

http_status() {
    curl -s -o /dev/null -w "%{http_code}" "$@"
}

http_body() {
    curl -s "$@"
}

# ---------------------------------------------------------------------------
echo ""
echo "=== KSeF Backend Smoke Test ==="
echo "BASE_URL: $BASE_URL"
echo ""

# 1. Health (DB liveness)
echo "--- 1. Health ---"
HEALTH_STATUS=$(http_status "$BASE_URL/health")
HEALTH_BODY=$(http_body "$BASE_URL/health")
check "GET /health → 200"            "$HEALTH_STATUS"            "200"
check "GET /health → status:ok"      "$HEALTH_BODY"              '"status":"ok"'

# 2. Docs / UI
echo "--- 2. Docs & UI ---"
DOCS_STATUS=$(http_status "$BASE_URL/docs")
UI_STATUS=$(http_status "$BASE_URL/ui" -L)
check "GET /docs → 200"    "$DOCS_STATUS"  "200"
check "GET /ui → 200"      "$UI_STATUS"    "200"

# 3. Login
echo "--- 3. Auth ---"
LOGIN_BODY=$(http_body -X POST "$BASE_URL/api/v1/auth/login" \
    -H "Content-Type: application/x-www-form-urlencoded" \
    -d "username=$ADMIN_USER&password=$ADMIN_PASS")
TOKEN=$(echo "$LOGIN_BODY" | jq -r '.access_token // empty')
check "POST /auth/login → token" "$TOKEN" "eyJ"

# 4. Create invoice
echo "--- 4. Invoice flow ---"
BUYER_BODY=$(http_body -X GET "$BASE_URL/api/v1/contractors?nip=5260001572" \
    -H "Authorization: Bearer $TOKEN" 2>/dev/null)
BUYER_ID=$(echo "$BUYER_BODY" | jq -r '.[0].id // empty')
if [[ -z "$BUYER_ID" ]]; then
    # seed a contractor first via override
    SEED=$(http_body -X POST "$BASE_URL/api/v1/contractors" \
        -H "Authorization: Bearer $TOKEN" \
        -H "Content-Type: application/json" \
        -d '{"nip":"5260001572","name":"Test Buyer","source":"manual"}' 2>/dev/null || echo "{}")
    BUYER_ID=$(echo "$SEED" | jq -r '.id // empty')
fi

INVOICE_PAYLOAD=$(cat <<EOF
{
  "buyer_id": "$BUYER_ID",
  "issue_date": "2026-04-05",
  "sale_date": "2026-04-05",
  "currency": "PLN",
  "items": [
    {
      "name": "Smoke test item",
      "quantity": "1",
      "unit": "szt",
      "unit_price_net": "100.00",
      "vat_rate": "23"
    }
  ]
}
EOF
)

CREATE_RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "$BASE_URL/api/v1/invoices" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d "$INVOICE_PAYLOAD")
CREATE_BODY=$(echo "$CREATE_RESPONSE" | head -n -1)
CREATE_STATUS=$(echo "$CREATE_RESPONSE" | tail -n 1)
INVOICE_ID=$(echo "$CREATE_BODY" | jq -r '.id // empty')
READY_INVOICE_ID="$INVOICE_ID"
check "POST /invoices → 201"        "$CREATE_STATUS" "201"
check "POST /invoices → id present" "$INVOICE_ID"    "-"

# 5. List invoices
LIST_STATUS=$(http_status "$BASE_URL/api/v1/invoices" \
    -H "Authorization: Bearer $TOKEN")
check "GET /invoices → 200" "$LIST_STATUS" "200"

# 6. Mark as ready
if [[ -n "$READY_INVOICE_ID" ]]; then
    READY_STATUS=$(http_status -X POST "$BASE_URL/api/v1/invoices/$READY_INVOICE_ID/mark-ready" \
        -H "Authorization: Bearer $TOKEN")
    READY_BODY=$(http_body -X POST "$BASE_URL/api/v1/invoices/$READY_INVOICE_ID/mark-ready" \
        -H "Authorization: Bearer $TOKEN")
    check "POST /invoices/{id}/mark-ready → 200"         "$READY_STATUS" "200"
    check "POST /invoices/{id}/mark-ready → number_local" "$READY_BODY"  "FV/"
fi

# 7. Payment CSV import
echo "--- 5. Payments ---"
CSV_FILE=$(mktemp /tmp/smoke_XXXX.csv)
printf 'transaction_date,amount,currency,title\n2026-04-05,123.00,PLN,Smoke test przelew\n' > "$CSV_FILE"
CSV_STATUS=$(http_status -X POST "$BASE_URL/api/v1/payments/import" \
    -H "Authorization: Bearer $TOKEN" \
    -F "file=@$CSV_FILE;type=text/csv")
rm -f "$CSV_FILE"
check "POST /payments/import → 200" "$CSV_STATUS" "200"

# 8. Contractor override
if [[ -n "$BUYER_ID" ]]; then
    echo "--- 6. Contractor override ---"
    OVR_STATUS=$(http_status -X PATCH "$BASE_URL/api/v1/contractors/$BUYER_ID/override" \
        -H "Authorization: Bearer $TOKEN" \
        -H "Content-Type: application/json" \
        -d '{"name":"Smoke Override Name"}')
    check "PATCH /contractors/{id}/override → 200" "$OVR_STATUS" "200"
fi

# 9. Transmissions list
echo "--- 7. Transmissions ---"
TX_STATUS=$(http_status "$BASE_URL/api/v1/transmissions" \
    -H "Authorization: Bearer $TOKEN")
check "GET /transmissions → 200" "$TX_STATUS" "200"

# 10. Non-existent resource → 404
echo "--- 8. Error handling ---"
NOT_FOUND=$(http_status "$BASE_URL/api/v1/invoices/00000000-0000-0000-0000-000000000000" \
    -H "Authorization: Bearer $TOKEN")
check "GET /invoices/non-existent → 404" "$NOT_FOUND" "404"

# 11. Unauthorized → 401
UNAUTH=$(http_status "$BASE_URL/api/v1/invoices")
check "GET /invoices without token → 401" "$UNAUTH" "401"

# ---------------------------------------------------------------------------
echo ""
echo "=== WYNIK ==="
echo "PASS: $PASS"
echo "FAIL: $FAIL"
if [[ ${#ERRORS[@]} -gt 0 ]]; then
    echo "Nieudane testy:"
    for e in "${ERRORS[@]}"; do echo "  - $e"; done
    exit 1
else
    echo "Wszystkie OK"
    exit 0
fi
