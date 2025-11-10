#!/usr/bin/env python3
"""Script to create two scraping sources for testing.

Creates:
1. Aiara Koudala - Multi-noticia (múltiples noticias en una URL)
2. Prentsa Araba - Index (árbol de noticias con enlaces)

Both run daily at 08:00
"""

import asyncio
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.supabase_client import get_supabase_client
from utils.scraper_helpers import create_scraping_source


async def main():
    """Create two scraping sources."""
    print("=" * 60)
    print("Creating Scraping Sources")
    print("=" * 60)
    
    supabase = get_supabase_client()
    
    # Get first company
    print("\n🔍 Looking for company...")
    companies = supabase.client.table('companies').select('id, company_name').limit(1).execute()
    
    if not companies.data:
        print('❌ No companies found. Please create a company first.')
        return
    
    company = companies.data[0]
    company_id = company['id']
    print(f'✅ Using company: {company["company_name"]} ({company_id})')
    
    # Get first client for this company
    print("\n🔍 Looking for client...")
    clients = supabase.client.table('clients').select('client_id').eq(
        'company_id', company_id
    ).limit(1).execute()
    
    if not clients.data:
        print('❌ No clients found for this company. Please create a client first.')
        return
    
    client_id = clients.data[0]['client_id']
    print(f'✅ Using client_id: {client_id}')
    
    # Source 1: Aiara Koudala (multi-noticia)
    print("\n" + "=" * 60)
    print("SOURCE 1: Aiara Koudala - Multi-noticia")
    print("=" * 60)
    print("URL: https://www.aiarakoudala.eus/es/noticias")
    print("Type: article (múltiples noticias en la misma página)")
    print("Schedule: Daily at 08:00")
    
    result1 = await create_scraping_source(
        company_id=company_id,
        client_id=client_id,
        url='https://www.aiarakoudala.eus/es/noticias',
        source_name='Aiara Koudala - Noticias',
        url_type='article',
        cron_schedule='08:00',
        is_active=True,
        description='Portal de noticias de Aiara Koudala - múltiples noticias en la misma página',
        tags=['scraping', 'aiara-koudala', 'euskadi', 'multi-noticia']
    )
    
    if result1['success']:
        print(f'\n✅ Source created successfully!')
        print(f'   Source ID: {result1["source_id"]}')
        print(f'   Source Code: {result1["source"]["source_code"]}')
    else:
        print(f'\n❌ Error creating source: {result1.get("error")}')
    
    # Source 2: Prentsa Araba (index)
    print("\n" + "=" * 60)
    print("SOURCE 2: Prentsa Araba - Índice de Noticias")
    print("=" * 60)
    print("URL: https://prentsa.araba.eus/es/noticias")
    print("Type: index (árbol de noticias con enlaces a artículos)")
    print("Schedule: Daily at 08:00")
    
    result2 = await create_scraping_source(
        company_id=company_id,
        client_id=client_id,
        url='https://prentsa.araba.eus/es/noticias',
        source_name='Prentsa Araba - Índice',
        url_type='index',
        cron_schedule='08:00',
        is_active=True,
        description='Oficina de Prensa de Álava - índice de noticias',
        tags=['scraping', 'prentsa-araba', 'alava', 'euskadi', 'index']
    )
    
    if result2['success']:
        print(f'\n✅ Source created successfully!')
        print(f'   Source ID: {result2["source_id"]}')
        print(f'   Source Code: {result2["source"]["source_code"]}')
    else:
        print(f'\n❌ Error creating source: {result2.get("error")}')
    
    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    
    success_count = sum([1 for r in [result1, result2] if r['success']])
    print(f'Sources created: {success_count} / 2')
    
    if success_count > 0:
        print('\n📅 Schedule:')
        print('   Both sources run daily at 08:00 UTC')
        print('\n🔄 Scheduler:')
        print('   Sources will be picked up automatically')
        print('   (scheduler refreshes every 5 minutes)')
        print('\n📊 Monitoring:')
        print('   Check monitored_urls table for tracking')
        print('   Check url_change_log for change history')
    
    print("\n" + "=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
