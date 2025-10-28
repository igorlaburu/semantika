"""Workflow factory for loading company-specific workflows.

Dynamically loads workflows based on company_code.
Falls back to default workflow if no custom workflow exists.
"""

import importlib
from typing import Dict, Any, Optional
from workflows.base_workflow import BaseWorkflow
from utils.logger import get_logger

logger = get_logger("workflow_factory")


def get_workflow(company_code: str, company_settings: Optional[Dict[str, Any]] = None) -> BaseWorkflow:
    """Get workflow instance for company.
    
    Args:
        company_code: Company identifier (e.g., "acme", "globex")
        company_settings: Company settings from database
        
    Returns:
        Workflow instance (custom or default)
    """
    try:
        # Try to load company-specific workflow
        module_path = f"workflows.{company_code}.{company_code}_workflow"
        module = importlib.import_module(module_path)
        
        # Look for class named {CompanyCode}Workflow
        class_name = f"{company_code.title()}Workflow"
        workflow_class = getattr(module, class_name)
        
        logger.info("custom_workflow_loaded", company_code=company_code, class_name=class_name)
        return workflow_class(company_code, company_settings)
        
    except (ImportError, AttributeError) as e:
        # Fallback to default workflow
        logger.info("fallback_to_default_workflow", company_code=company_code, reason=str(e))
        
        from workflows.default.default_workflow import DefaultWorkflow
        return DefaultWorkflow(company_code, company_settings)


def list_available_workflows() -> Dict[str, str]:
    """List all available workflows.
    
    Returns:
        Dict mapping company_code to workflow class name
    """
    import os
    import glob
    
    workflows = {}
    
    # Get workflows directory
    workflows_dir = os.path.dirname(__file__)
    
    # Look for company directories (excluding 'default')
    for company_dir in glob.glob(os.path.join(workflows_dir, "*")):
        if os.path.isdir(company_dir):
            company_code = os.path.basename(company_dir)
            
            if company_code == "default":
                workflows["default"] = "DefaultWorkflow"
                continue
                
            # Look for workflow file
            workflow_file = os.path.join(company_dir, f"{company_code}_workflow.py")
            if os.path.exists(workflow_file):
                workflows[company_code] = f"{company_code.title()}Workflow"
    
    return workflows


# Example usage:
# workflow = get_workflow("acme", {"llm_model": "anthropic/claude-3.5-sonnet"})
# result = await workflow.process_content(source_content)