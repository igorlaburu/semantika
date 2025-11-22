#!/bin/bash
# Admin CLI - Company Onboarding Script
# Creates company + client + API key + Manual source + organization + auth user

set -e  # Exit on error

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${BLUE}╔════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║    EKIMEN - Company Onboarding CLI        ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════╝${NC}"
echo ""

# Input variables
echo -ne "${YELLOW}Company Name: ${NC}"
read COMPANY_NAME

echo -ne "${YELLOW}Company CIF: ${NC}"
read COMPANY_CIF

echo -ne "${YELLOW}Tier [starter/pro/unlimited] (default: pro): ${NC}"
read TIER
TIER=${TIER:-pro}

echo -ne "${YELLOW}User Email: ${NC}"
read USER_EMAIL

echo -ne "${YELLOW}User Password: ${NC}"
read -s USER_PASSWORD
echo ""

echo -ne "${YELLOW}User Name (optional): ${NC}"
read USER_NAME

echo ""
echo -e "${GREEN}══════════════════════════════════════════${NC}"
echo -e "${GREEN}  Step 1/2: Creating Company${NC}"
echo -e "${GREEN}══════════════════════════════════════════${NC}"

# Create company (includes Manual source)
COMPANY_OUTPUT=$(docker exec ekimen_semantika-semantika-api-1 python cli.py create-company \
  --name "$COMPANY_NAME" \
  --cif "$COMPANY_CIF" \
  --tier "$TIER" 2>&1)

echo "$COMPANY_OUTPUT"

# Extract company_id from output (last UUID in output)
COMPANY_ID=$(echo "$COMPANY_OUTPUT" | grep -oE '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}' | tail -1)

if [ -z "$COMPANY_ID" ]; then
    echo -e "${YELLOW}⚠️  Warning: Could not extract company_id automatically${NC}"
    read -p "$(echo -e ${YELLOW}Please enter company_id manually: ${NC})" COMPANY_ID
fi

echo ""
echo -e "${GREEN}══════════════════════════════════════════${NC}"
echo -e "${GREEN}  Step 2/2: Creating Auth User${NC}"
echo -e "${GREEN}══════════════════════════════════════════${NC}"

# Create auth user
if [ -z "$USER_NAME" ]; then
    docker exec ekimen_semantika-semantika-api-1 python cli.py create-auth-user \
      --email "$USER_EMAIL" \
      --password "$USER_PASSWORD" \
      --company-id "$COMPANY_ID"
else
    docker exec ekimen_semantika-semantika-api-1 python cli.py create-auth-user \
      --email "$USER_EMAIL" \
      --password "$USER_PASSWORD" \
      --company-id "$COMPANY_ID" \
      --name "$USER_NAME"
fi

echo ""
echo -e "${BLUE}╔════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║         🎉 Onboarding Complete!           ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${GREEN}Next steps:${NC}"
echo -e "  1. Share API key and login credentials with client"
echo -e "  2. Client can login at: ${BLUE}https://press.ekimen.ai${NC}"
echo -e "  3. Add additional sources via Supabase UI if needed"
echo ""
