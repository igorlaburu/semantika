"""ACME Corp custom workflow implementation.

Example of company-specific workflow with custom processing.
"""

from typing import Dict, Any
from sources.base_source import SourceContent
from workflows.default.default_workflow import DefaultWorkflow
from utils.openrouter_client import get_openrouter_client
from langchain_core.prompts import ChatPromptTemplate


class AcmeWorkflow(DefaultWorkflow):
    """ACME Corp custom workflow with legal compliance checking."""

    async def generate_context_unit(self, source_content: SourceContent) -> Dict[str, Any]:
        """Generate context unit with ACME-specific processing."""
        # Start with standard processing
        context_unit = await super().generate_context_unit(source_content)
        
        # ACME custom: Add legal compliance check
        legal_status = await self.check_legal_compliance(context_unit["raw_text"])
        context_unit["legal_compliance"] = legal_status
        
        # ACME custom: Add priority classification
        priority = await self.classify_priority(context_unit["raw_text"])
        context_unit["priority_level"] = priority
        
        self.logger.info(
            "acme_context_unit_enhanced",
            legal_status=legal_status.get("status"),
            priority_level=priority
        )
        
        return context_unit

    async def analyze_content(self, source_content: SourceContent, context_unit: Dict[str, Any]) -> Dict[str, Any]:
        """ACME-specific content analysis."""
        # Get base analysis
        analysis = await super().analyze_content(source_content, context_unit)
        
        # ACME custom: Financial impact assessment
        financial_impact = await self.assess_financial_impact(context_unit["raw_text"])
        analysis["financial_impact"] = financial_impact
        
        # ACME custom: Brand mention detection
        brand_mentions = await self.detect_brand_mentions(context_unit["raw_text"])
        analysis["brand_mentions"] = brand_mentions
        
        return analysis

    async def custom_processing(
        self, 
        source_content: SourceContent, 
        context_unit: Dict[str, Any], 
        analysis: Dict[str, Any]
    ) -> Dict[str, Any]:
        """ACME-specific custom processing."""
        custom_data = {}
        
        # ACME workflow: Generate internal alert if high priority + legal issues
        if (context_unit.get("priority_level") == "high" and 
            context_unit.get("legal_compliance", {}).get("status") == "review_required"):
            
            custom_data["alert"] = {
                "type": "legal_priority",
                "message": "High priority content requires legal review",
                "recommended_actions": [
                    "Forward to legal department",
                    "Review within 24 hours",
                    "Assess compliance impact"
                ]
            }
        
        # ACME workflow: Competitor analysis
        if analysis.get("brand_mentions", {}).get("competitors"):
            custom_data["competitor_analysis"] = await self.analyze_competitors(
                context_unit["raw_text"],
                analysis["brand_mentions"]["competitors"]
            )
        
        return custom_data

    async def check_legal_compliance(self, text: str) -> Dict[str, Any]:
        """Check content for legal compliance issues."""
        try:
            openrouter = get_openrouter_client()
            
            # ACME-specific legal compliance prompt
            legal_prompt = ChatPromptTemplate.from_messages([
                ("system", """You are a legal compliance analyst for ACME Corp.
                
Analyze the content for potential legal issues:
- Privacy/GDPR violations
- Regulatory compliance (SEC, FDA, etc.)
- Intellectual property concerns
- Contract/NDA violations
- Defamation risks

Respond in JSON format:
{"status": "compliant|review_required|violation", "issues": [...], "recommendations": [...]}"""),
                ("user", "Analyze this content for legal compliance:\n\n{text}")
            ])
            
            # This would use TrackedChatOpenAI automatically
            response = await openrouter.llm_fast.ainvoke(
                legal_prompt.format_messages(text=text[:2000])
            )
            
            # Parse JSON response
            import json
            result = json.loads(response.content)
            
            self.logger.debug("legal_compliance_checked", status=result.get("status"))
            return result
            
        except Exception as e:
            self.logger.error("legal_compliance_error", error=str(e))
            return {"status": "unknown", "issues": [], "recommendations": []}

    async def classify_priority(self, text: str) -> str:
        """Classify content priority for ACME."""
        # Simple keyword-based classification for demo
        text_lower = text.lower()
        
        high_priority_keywords = [
            "urgent", "critical", "emergency", "lawsuit", "breach", 
            "regulatory", "compliance", "audit", "fine"
        ]
        
        medium_priority_keywords = [
            "important", "review", "deadline", "contract", "agreement"
        ]
        
        if any(keyword in text_lower for keyword in high_priority_keywords):
            return "high"
        elif any(keyword in text_lower for keyword in medium_priority_keywords):
            return "medium"
        else:
            return "low"

    async def assess_financial_impact(self, text: str) -> Dict[str, Any]:
        """Assess potential financial impact of content."""
        # Demo implementation - in reality would use LLM
        text_lower = text.lower()
        
        impact_indicators = {
            "revenue": ["sales", "revenue", "income", "profit"],
            "costs": ["cost", "expense", "fee", "fine", "penalty"],
            "market": ["stock", "market", "share", "valuation"]
        }
        
        detected_areas = []
        for area, keywords in impact_indicators.items():
            if any(keyword in text_lower for keyword in keywords):
                detected_areas.append(area)
        
        return {
            "impact_areas": detected_areas,
            "estimated_magnitude": "medium" if detected_areas else "low"
        }

    async def detect_brand_mentions(self, text: str) -> Dict[str, Any]:
        """Detect ACME and competitor brand mentions."""
        text_lower = text.lower()
        
        acme_mentions = text_lower.count("acme")
        
        competitors = ["globex", "initech", "wayne enterprises", "stark industries"]
        competitor_mentions = {}
        
        for competitor in competitors:
            count = text_lower.count(competitor)
            if count > 0:
                competitor_mentions[competitor] = count
        
        return {
            "acme_mentions": acme_mentions,
            "competitors": competitor_mentions,
            "total_brand_mentions": acme_mentions + sum(competitor_mentions.values())
        }

    async def analyze_competitors(self, text: str, competitors: Dict[str, int]) -> Dict[str, Any]:
        """Analyze competitor mentions in context."""
        # Demo analysis
        analysis = {
            "mentioned_competitors": list(competitors.keys()),
            "sentiment": "neutral",  # Would use LLM sentiment analysis
            "competitive_threats": [],
            "opportunities": []
        }
        
        # Simple heuristic analysis
        if len(competitors) > 2:
            analysis["competitive_threats"].append("Multiple competitors mentioned - market pressure")
        
        return analysis