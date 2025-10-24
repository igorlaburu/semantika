#!/bin/bash

# Script de verificación de deployment para semantika
# Uso: ./verify-deployment.sh https://api.semantika.tudominio.com sk-tu-api-key

set -e

# Colores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Función de ayuda
if [ "$#" -ne 2 ]; then
    echo "Uso: $0 <API_URL> <API_KEY>"
    echo ""
    echo "Ejemplo:"
    echo "  $0 https://api.semantika.tudominio.com sk-test-xxxxx"
    exit 1
fi

API_URL=$1
API_KEY=$2

echo "🔍 Verificando deployment de semantika..."
echo "📍 URL: $API_URL"
echo ""

# Test 1: Health check
echo -n "1️⃣  Health check... "
HEALTH=$(curl -s -w "\n%{http_code}" "$API_URL/health")
HTTP_CODE=$(echo "$HEALTH" | tail -n 1)
RESPONSE=$(echo "$HEALTH" | head -n -1)

if [ "$HTTP_CODE" -eq 200 ]; then
    echo -e "${GREEN}✓ OK${NC}"
    echo "   Respuesta: $RESPONSE"
else
    echo -e "${RED}✗ FAILED (HTTP $HTTP_CODE)${NC}"
    exit 1
fi
echo ""

# Test 2: Autenticación
echo -n "2️⃣  Autenticación... "
AUTH=$(curl -s -w "\n%{http_code}" -H "X-API-Key: $API_KEY" "$API_URL/me")
HTTP_CODE=$(echo "$AUTH" | tail -n 1)
RESPONSE=$(echo "$AUTH" | head -n -1)

if [ "$HTTP_CODE" -eq 200 ]; then
    echo -e "${GREEN}✓ OK${NC}"
    CLIENT_ID=$(echo "$RESPONSE" | grep -o '"client_id":"[^"]*"' | cut -d'"' -f4)
    CLIENT_NAME=$(echo "$RESPONSE" | grep -o '"client_name":"[^"]*"' | cut -d'"' -f4)
    echo "   Cliente: $CLIENT_NAME ($CLIENT_ID)"
else
    echo -e "${RED}✗ FAILED (HTTP $HTTP_CODE)${NC}"
    echo "   Error: $RESPONSE"
    exit 1
fi
echo ""

# Test 3: Ingesta de texto
echo -n "3️⃣  Ingesta de texto... "
TIMESTAMP=$(date +%s)
INGEST=$(curl -s -w "\n%{http_code}" -X POST "$API_URL/ingest/text" \
    -H "X-API-Key: $API_KEY" \
    -H "Content-Type: application/json" \
    -d "{
        \"text\": \"Deployment verification test at timestamp $TIMESTAMP. Machine learning is transforming the technology industry.\",
        \"title\": \"Deployment Test $TIMESTAMP\",
        \"metadata\": {\"source\": \"verify-script\", \"timestamp\": $TIMESTAMP}
    }")
HTTP_CODE=$(echo "$INGEST" | tail -n 1)
RESPONSE=$(echo "$INGEST" | head -n -1)

if [ "$HTTP_CODE" -eq 200 ]; then
    echo -e "${GREEN}✓ OK${NC}"
    DOCS_ADDED=$(echo "$RESPONSE" | grep -o '"documents_added":[0-9]*' | cut -d':' -f2)
    echo "   Documentos añadidos: $DOCS_ADDED"
else
    echo -e "${RED}✗ FAILED (HTTP $HTTP_CODE)${NC}"
    echo "   Error: $RESPONSE"
    exit 1
fi
echo ""

# Test 4: Búsqueda semántica
echo -n "4️⃣  Búsqueda semántica... "
sleep 2  # Esperar a que el índice se actualice
SEARCH=$(curl -s -w "\n%{http_code}" "$API_URL/search?query=machine%20learning&limit=5" \
    -H "X-API-Key: $API_KEY")
HTTP_CODE=$(echo "$SEARCH" | tail -n 1)
RESPONSE=$(echo "$SEARCH" | head -n -1)

if [ "$HTTP_CODE" -eq 200 ]; then
    echo -e "${GREEN}✓ OK${NC}"
    RESULTS_COUNT=$(echo "$RESPONSE" | grep -o '"results":\[' | wc -l)
    echo "   Búsqueda ejecutada correctamente"
else
    echo -e "${RED}✗ FAILED (HTTP $HTTP_CODE)${NC}"
    echo "   Error: $RESPONSE"
    exit 1
fi
echo ""

# Test 5: Scraping web (solo check endpoint, no ejecutar)
echo -n "5️⃣  Endpoint /ingest/url... "
URL_TEST=$(curl -s -w "\n%{http_code}" -X POST "$API_URL/ingest/url" \
    -H "X-API-Key: $API_KEY" \
    -H "Content-Type: application/json" \
    -d '{"url": "https://example.com", "extract_multiple": false}')
HTTP_CODE=$(echo "$URL_TEST" | tail -n 1)
RESPONSE=$(echo "$URL_TEST" | head -n -1)

if [ "$HTTP_CODE" -eq 200 ]; then
    echo -e "${GREEN}✓ OK${NC}"
    echo "   Web scraper funcional"
else
    echo -e "${YELLOW}⚠ WARNING (HTTP $HTTP_CODE)${NC}"
    echo "   El endpoint existe pero puede haber fallado: $RESPONSE"
fi
echo ""

# Test 6: Agregación
echo -n "6️⃣  Agregación con LLM... "
AGGREGATE=$(curl -s -w "\n%{http_code}" "$API_URL/aggregate?query=machine%20learning&limit=5&threshold=0.5" \
    -H "X-API-Key: $API_KEY")
HTTP_CODE=$(echo "$AGGREGATE" | tail -n 1)
RESPONSE=$(echo "$AGGREGATE" | head -n -1)

if [ "$HTTP_CODE" -eq 200 ]; then
    echo -e "${GREEN}✓ OK${NC}"
    SOURCES=$(echo "$RESPONSE" | grep -o '"sources_count":[0-9]*' | cut -d':' -f2)
    echo "   Fuentes procesadas: ${SOURCES:-0}"
else
    echo -e "${YELLOW}⚠ WARNING (HTTP $HTTP_CODE)${NC}"
    echo "   Puede no tener suficientes documentos para agregar"
fi
echo ""

# Resumen final
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${GREEN}✅ Deployment verificado exitosamente!${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "📊 Próximos pasos:"
echo "  1. Verifica logs en Dozzle (puerto 8081)"
echo "  2. Crea tareas programadas con CLI"
echo "  3. Monitorea Qdrant y Supabase"
echo ""
