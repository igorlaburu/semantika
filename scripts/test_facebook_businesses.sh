#!/bin/bash
# =============================================================================
# test_facebook_businesses.sh
# =============================================================================
# Script para probar el endpoint GET /oauth/facebook/businesses
#
# Este endpoint es necesario para pasar el Facebook App Review del permiso
# "business_management". Demuestra que la app puede listar los Business
# Managers asociados al usuario autenticado.
#
# USO:
#   ./scripts/test_facebook_businesses.sh <JWT_TOKEN>
#
# OBTENER EL TOKEN:
#   1. Inicia sesión en el frontend de Ekimen
#   2. Abre DevTools (F12) → Application → Local Storage
#   3. Copia el valor de 'access_token'
#
# EJEMPLO:
#   ./scripts/test_facebook_businesses.sh eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
#
# RESPUESTA ESPERADA:
#   {
#     "success": true,
#     "businesses": [
#       {
#         "id": "123456789",
#         "name": "Mi Business Manager",
#         "primary_page": {...}
#       }
#     ]
#   }
#
# REQUISITOS:
#   - Usuario debe tener cuenta de Facebook conectada en Ekimen
#   - La cuenta de Facebook debe tener acceso a al menos un Business Manager
# =============================================================================

API_BASE_URL="${API_BASE_URL:-https://api.ekimen.ai}"

if [ -z "$1" ]; then
    echo "Error: Se requiere un JWT token como parámetro"
    echo ""
    echo "Uso: $0 <JWT_TOKEN>"
    echo ""
    echo "Obtener el token:"
    echo "  1. Inicia sesión en el frontend de Ekimen"
    echo "  2. Abre DevTools (F12) → Application → Local Storage"
    echo "  3. Copia el valor de 'access_token'"
    exit 1
fi

TOKEN="$1"

echo "Llamando a GET /oauth/facebook/businesses..."
echo "API: $API_BASE_URL"
echo ""

curl -s -X GET \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    "$API_BASE_URL/oauth/facebook/businesses" | python3 -m json.tool

echo ""
