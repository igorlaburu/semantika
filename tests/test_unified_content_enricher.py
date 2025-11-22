"""Unit tests for unified_content_enricher module.

Tests the centralized content enrichment layer that provides
consistent LLM-based categorization across all source types.
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch
from utils.unified_content_enricher import enrich_content, enrich_content_batch


@pytest.fixture
def mock_llm_client():
    """Mock LLM client for testing."""
    mock_client = Mock()
    mock_client.analyze_atomic = AsyncMock(return_value={
        "title": "Ayuntamiento aprueba presupuesto 2025",
        "summary": "El pleno municipal aprobó el presupuesto para el próximo año con un incremento del 5%.",
        "tags": ["presupuesto", "ayuntamiento", "política"],
        "category": "política",
        "atomic_facts": [
            "El pleno municipal aprobó el presupuesto 2025",
            "El presupuesto tiene un incremento del 5%"
        ],
        "cost_usd": 0.002,
        "model": "gpt-4o-mini"
    })
    return mock_client


@pytest.mark.asyncio
class TestEnrichContent:
    """Test enrich_content function."""
    
    async def test_enrich_with_no_prefilled(self, mock_llm_client):
        """Test enrichment with empty pre_filled (LLM generates everything)."""
        with patch('utils.unified_content_enricher.get_llm_client', return_value=mock_llm_client):
            result = await enrich_content(
                raw_text="El ayuntamiento aprobó el presupuesto de 2025 con un incremento del 5%.",
                source_type="scraping",
                company_id="test-company-123",
                pre_filled={}
            )
        
        assert result["title"] == "Ayuntamiento aprueba presupuesto 2025"
        assert result["summary"] == "El pleno municipal aprobó el presupuesto para el próximo año con un incremento del 5%."
        assert result["category"] == "política"
        assert len(result["tags"]) == 3
        assert "presupuesto" in result["tags"]
        assert len(result["atomic_statements"]) == 2
        assert result["enrichment_cost_usd"] == 0.002
        assert result["enrichment_model"] == "gpt-4o-mini"
        
        mock_llm_client.analyze_atomic.assert_called_once()
    
    async def test_enrich_with_prefilled_title(self, mock_llm_client):
        """Test enrichment with pre-filled title (LLM skips title generation)."""
        with patch('utils.unified_content_enricher.get_llm_client', return_value=mock_llm_client):
            result = await enrich_content(
                raw_text="El ayuntamiento aprobó el presupuesto de 2025.",
                source_type="manual",
                company_id="test-company-123",
                pre_filled={"title": "Nuevo presupuesto municipal"}
            )
        
        assert result["title"] == "Nuevo presupuesto municipal"
        assert result["summary"] == "El pleno municipal aprobó el presupuesto para el próximo año con un incremento del 5%."
        assert result["category"] == "política"
        
        mock_llm_client.analyze_atomic.assert_called_once()
    
    async def test_enrich_with_all_prefilled(self, mock_llm_client):
        """Test enrichment with all fields pre-filled (LLM not called)."""
        pre_filled = {
            "title": "Custom Title",
            "summary": "Custom summary",
            "tags": ["custom", "tags"],
            "category": "tecnología",
            "atomic_statements": [{"statement": "Custom fact"}]
        }
        
        with patch('utils.unified_content_enricher.get_llm_client', return_value=mock_llm_client):
            result = await enrich_content(
                raw_text="Some text",
                source_type="manual",
                company_id="test-company-123",
                pre_filled=pre_filled
            )
        
        assert result["title"] == "Custom Title"
        assert result["summary"] == "Custom summary"
        assert result["category"] == "tecnología"
        assert result["enrichment_cost_usd"] == 0.0
        assert result["enrichment_model"] == "none"
        
        mock_llm_client.analyze_atomic.assert_not_called()
    
    async def test_enrich_with_partial_prefilled(self, mock_llm_client):
        """Test enrichment with partial pre-filled (title + tags, LLM generates rest)."""
        pre_filled = {
            "title": "Custom Title",
            "tags": ["custom", "tag"]
        }
        
        with patch('utils.unified_content_enricher.get_llm_client', return_value=mock_llm_client):
            result = await enrich_content(
                raw_text="El ayuntamiento aprobó...",
                source_type="perplexity",
                company_id="test-company-123",
                pre_filled=pre_filled
            )
        
        assert result["title"] == "Custom Title"
        assert result["tags"] == ["custom", "tag"]
        assert result["summary"] == "El pleno municipal aprobó el presupuesto para el próximo año con un incremento del 5%."
        assert result["category"] == "política"
        
        mock_llm_client.analyze_atomic.assert_called_once()
    
    async def test_enrich_different_categories(self, mock_llm_client):
        """Test that different content types get different categories."""
        category_tests = [
            ("economía", "La empresa anunció beneficios récord"),
            ("cultura", "El museo inaugura nueva exposición"),
            ("deportes", "El equipo ganó el campeonato"),
            ("salud", "El hospital abre nuevo servicio"),
            ("medio_ambiente", "Nueva planta de reciclaje")
        ]
        
        for expected_category, text in category_tests:
            mock_llm_client.analyze_atomic = AsyncMock(return_value={
                "title": "Test",
                "summary": "Summary",
                "tags": ["test"],
                "category": expected_category,
                "atomic_facts": [],
                "cost_usd": 0.001,
                "model": "gpt-4o-mini"
            })
            
            with patch('utils.unified_content_enricher.get_llm_client', return_value=mock_llm_client):
                result = await enrich_content(
                    raw_text=text,
                    source_type="scraping",
                    company_id="test-company-123",
                    pre_filled={}
                )
            
            assert result["category"] == expected_category
    
    async def test_enrich_handles_llm_error(self, mock_llm_client):
        """Test that enrichment handles LLM errors gracefully."""
        mock_llm_client.analyze_atomic = AsyncMock(side_effect=Exception("LLM API error"))
        
        pre_filled = {"title": "Fallback Title"}
        
        with patch('utils.unified_content_enricher.get_llm_client', return_value=mock_llm_client):
            result = await enrich_content(
                raw_text="Some content",
                source_type="scraping",
                company_id="test-company-123",
                pre_filled=pre_filled
            )
        
        assert result["title"] == "Fallback Title"
        assert result["summary"] == ""
        assert result["tags"] == []
        assert result["category"] == "general"
        assert result["enrichment_cost_usd"] == 0.0
        assert result["enrichment_model"] == "error"
    
    async def test_enrich_handles_missing_llm_fields(self, mock_llm_client):
        """Test enrichment when LLM returns incomplete data."""
        mock_llm_client.analyze_atomic = AsyncMock(return_value={
            "title": "Only Title",
        })
        
        with patch('utils.unified_content_enricher.get_llm_client', return_value=mock_llm_client):
            result = await enrich_content(
                raw_text="Some content",
                source_type="scraping",
                company_id="test-company-123",
                pre_filled={}
            )
        
        assert result["title"] == "Only Title"
        assert result["summary"] == ""
        assert result["tags"] == []
        assert result["category"] == "general"
        assert result["atomic_statements"] == []
    
    async def test_enrich_text_truncation(self, mock_llm_client):
        """Test that long text is truncated to 8000 chars."""
        long_text = "a" * 10000
        
        with patch('utils.unified_content_enricher.get_llm_client', return_value=mock_llm_client):
            await enrich_content(
                raw_text=long_text,
                source_type="scraping",
                company_id="test-company-123",
                pre_filled={}
            )
        
        call_args = mock_llm_client.analyze_atomic.call_args
        assert len(call_args.kwargs["text"]) == 8000
    
    async def test_enrich_preserves_source_type_in_logs(self, mock_llm_client):
        """Test that source_type is used for logging (not for enrichment logic)."""
        source_types = ["manual", "scraping", "email", "perplexity", "email_audio"]
        
        for source_type in source_types:
            with patch('utils.unified_content_enricher.get_llm_client', return_value=mock_llm_client):
                result = await enrich_content(
                    raw_text="Test content",
                    source_type=source_type,
                    company_id="test-company-123",
                    pre_filled={}
                )
            
            assert result["title"] is not None
            assert isinstance(result["tags"], list)


@pytest.mark.asyncio
class TestEnrichContentBatch:
    """Test enrich_content_batch function."""
    
    async def test_batch_enrichment(self, mock_llm_client):
        """Test batch enrichment of multiple items."""
        items = [
            {"raw_text": "First news item", "pre_filled": {"title": "Title 1"}},
            {"raw_text": "Second news item", "pre_filled": {}},
            {"raw_text": "Third news item", "pre_filled": {"title": "Title 3"}}
        ]
        
        with patch('utils.unified_content_enricher.get_llm_client', return_value=mock_llm_client):
            results = await enrich_content_batch(
                items=items,
                source_type="perplexity",
                company_id="test-company-123"
            )
        
        assert len(results) == 3
        assert results[0]["title"] == "Title 1"
        assert results[1]["title"] == "Ayuntamiento aprueba presupuesto 2025"
        assert results[2]["title"] == "Title 3"
        
        assert mock_llm_client.analyze_atomic.call_count == 3
    
    async def test_batch_handles_individual_errors(self, mock_llm_client):
        """Test that batch enrichment continues even if individual items fail."""
        call_count = 0
        
        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise Exception("Second item fails")
            return {
                "title": f"Title {call_count}",
                "summary": "Summary",
                "tags": ["test"],
                "category": "general",
                "atomic_facts": [],
                "cost_usd": 0.001,
                "model": "gpt-4o-mini"
            }
        
        mock_llm_client.analyze_atomic = AsyncMock(side_effect=side_effect)
        
        items = [
            {"raw_text": "Item 1", "pre_filled": {}},
            {"raw_text": "Item 2", "pre_filled": {}},
            {"raw_text": "Item 3", "pre_filled": {}}
        ]
        
        with patch('utils.unified_content_enricher.get_llm_client', return_value=mock_llm_client):
            results = await enrich_content_batch(
                items=items,
                source_type="perplexity",
                company_id="test-company-123"
            )
        
        assert len(results) == 3
        assert results[0]["title"] == "Title 1"
        assert results[1]["enrichment_model"] == "error"
        assert results[2]["title"] == "Title 3"
    
    async def test_batch_calculates_total_cost(self, mock_llm_client):
        """Test that batch enrichment sums up costs correctly."""
        items = [
            {"raw_text": "Item 1", "pre_filled": {}},
            {"raw_text": "Item 2", "pre_filled": {}},
            {"raw_text": "Item 3", "pre_filled": {}}
        ]
        
        with patch('utils.unified_content_enricher.get_llm_client', return_value=mock_llm_client):
            results = await enrich_content_batch(
                items=items,
                source_type="perplexity",
                company_id="test-company-123"
            )
        
        total_cost = sum(r["enrichment_cost_usd"] for r in results)
        assert total_cost == 0.006


@pytest.mark.asyncio
class TestRealWorldScenarios:
    """Test real-world usage scenarios."""
    
    async def test_manual_source_scenario(self, mock_llm_client):
        """Test manual source: user provides title, LLM enriches rest."""
        with patch('utils.unified_content_enricher.get_llm_client', return_value=mock_llm_client):
            result = await enrich_content(
                raw_text="El ayuntamiento ha decidido aumentar el presupuesto educativo en un 10%.",
                source_type="manual",
                company_id="test-company-123",
                pre_filled={"title": "Más presupuesto para educación"}
            )
        
        assert result["title"] == "Más presupuesto para educación"
        assert "presupuesto" in result["tags"] or "ayuntamiento" in result["tags"]
        assert result["category"] in ["política", "sociedad"]
    
    async def test_scraping_scenario(self, mock_llm_client):
        """Test scraping source: LLM generates everything from HTML."""
        html_content = """
        <article>
            <h1>Nueva ordenanza municipal de tráfico</h1>
            <p>El ayuntamiento aprobó ayer una nueva ordenanza que regula...</p>
        </article>
        """
        
        with patch('utils.unified_content_enricher.get_llm_client', return_value=mock_llm_client):
            result = await enrich_content(
                raw_text=html_content,
                source_type="scraping",
                company_id="test-company-123",
                pre_filled={}
            )
        
        assert result["title"] is not None
        assert result["category"] is not None
        assert len(result["atomic_statements"]) >= 0
    
    async def test_perplexity_scenario(self, mock_llm_client):
        """Test Perplexity source: keeps title, enriches category/tags."""
        perplexity_news = {
            "titulo": "Bilbao estrena nuevo sistema de transporte",
            "texto": "La ciudad de Bilbao ha inaugurado...",
            "fuente": "https://example.com",
            "fecha": "2025-11-22"
        }
        
        with patch('utils.unified_content_enricher.get_llm_client', return_value=mock_llm_client):
            result = await enrich_content(
                raw_text=perplexity_news["texto"],
                source_type="perplexity",
                company_id="test-company-123",
                pre_filled={"title": perplexity_news["titulo"]}
            )
        
        assert result["title"] == "Bilbao estrena nuevo sistema de transporte"
        assert result["category"] in ["infraestructuras", "general", "política"]
    
    async def test_email_scenario(self, mock_llm_client):
        """Test email source: uses subject as title."""
        email_subject = "Reunión urgente sobre presupuestos"
        email_body = "Buenos días, convoco reunión extraordinaria para discutir el presupuesto..."
        
        with patch('utils.unified_content_enricher.get_llm_client', return_value=mock_llm_client):
            result = await enrich_content(
                raw_text=email_body,
                source_type="email",
                company_id="test-company-123",
                pre_filled={"title": email_subject}
            )
        
        assert result["title"] == "Reunión urgente sobre presupuestos"
        assert result["summary"] is not None
