"""Publication targets endpoints."""

from datetime import datetime
from typing import Dict, Any

from fastapi import APIRouter, Depends, HTTPException

from utils.logger import get_logger
from utils.supabase_client import get_supabase_client
from utils.auth_dependencies import get_company_id_from_auth

logger = get_logger("api.publication_targets")
router = APIRouter(prefix="/api/v1/publication-targets", tags=["publication-targets"])


@router.get("")
async def list_publication_targets(
    company_id: str = Depends(get_company_id_from_auth)
) -> Dict[str, Any]:
    """Get all publication targets for the company.

    Returns list without encrypted credentials for security.
    """
    try:
        supabase = get_supabase_client()

        result = supabase.client.table("press_publication_targets")\
            .select("id, platform_type, name, base_url, is_default, is_active, created_at, updated_at, last_tested_at, test_result")\
            .eq("company_id", company_id)\
            .eq("is_active", True)\
            .order("created_at", desc=True)\
            .execute()

        logger.info("publication_targets_listed",
            company_id=company_id,
            count=len(result.data) if result.data else 0
        )

        return {
            "targets": result.data or []
        }

    except Exception as e:
        logger.error("list_publication_targets_error",
            company_id=company_id,
            error=str(e)
        )
        raise HTTPException(status_code=500, detail="Failed to fetch publication targets")


@router.post("")
async def create_publication_target(
    target_data: Dict[str, Any],
    company_id: str = Depends(get_company_id_from_auth)
) -> Dict[str, Any]:
    """Create a new publication target with encrypted credentials."""
    try:
        from utils.credential_manager import CredentialManager
        from publishers.publisher_factory import PublisherFactory

        logger.info("create_publication_target_request",
            company_id=company_id,
            received_fields=list(target_data.keys())
        )

        # Validate required fields
        required_fields = ['platform_type', 'name', 'base_url', 'credentials']
        for field in required_fields:
            if field not in target_data:
                logger.error("missing_required_field", field=field, received_data=target_data)
                raise HTTPException(status_code=400, detail=f"Missing required field: {field}")

        platform_type = target_data['platform_type']
        if platform_type not in PublisherFactory.get_supported_platforms():
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported platform: {platform_type}. Supported: {PublisherFactory.get_supported_platforms()}"
            )

        # Encrypt credentials
        credentials = target_data['credentials']
        masked_creds = CredentialManager.mask_credentials_for_logging(credentials)
        logger.info("publication_target_validation_passed",
            company_id=company_id,
            platform_type=platform_type,
            name=target_data['name'],
            base_url=target_data['base_url'],
            credentials=masked_creds
        )

        credentials_encrypted = CredentialManager.encrypt_credentials(credentials)

        # Test connection before saving
        publisher = PublisherFactory.create_publisher(
            platform_type,
            target_data['base_url'],
            credentials_encrypted
        )

        test_result = await publisher.test_connection()

        logger.info("wordpress_connection_test_result",
            company_id=company_id,
            platform_type=platform_type,
            base_url=target_data['base_url'],
            success=test_result.get('success'),
            message=test_result.get('message', 'No message')
        )

        if not test_result.get('success'):
            raise HTTPException(
                status_code=400,
                detail=f"Connection test failed: {test_result.get('message')}"
            )

        # Save to database
        supabase = get_supabase_client()

        insert_data = {
            "company_id": company_id,
            "platform_type": platform_type,
            "name": target_data['name'],
            "base_url": target_data['base_url'],
            "credentials_encrypted": credentials_encrypted.hex(),  # Convert bytes to hex string
            "is_default": target_data.get('is_default', False),
            "last_tested_at": datetime.utcnow().isoformat(),
            "test_result": test_result
        }

        result = supabase.client.table("press_publication_targets")\
            .insert(insert_data)\
            .execute()

        if not result.data:
            raise HTTPException(status_code=500, detail="Failed to create publication target")

        created_target = result.data[0]

        # Remove encrypted credentials from response
        response_data = {k: v for k, v in created_target.items() if k != 'credentials_encrypted'}

        logger.info("publication_target_created",
            target_id=created_target['id'],
            company_id=company_id,
            platform=platform_type,
            name=target_data['name']
        )

        return response_data

    except HTTPException:
        raise
    except Exception as e:
        logger.error("create_publication_target_error",
            company_id=company_id,
            target_data=str(target_data),
            error=str(e)
        )
        raise HTTPException(status_code=500, detail=f"Failed to create publication target: {str(e)}")


@router.get("/{target_id}")
async def get_publication_target(
    target_id: str,
    company_id: str = Depends(get_company_id_from_auth)
) -> Dict[str, Any]:
    """Get a specific publication target (without credentials)."""
    try:
        supabase = get_supabase_client()

        result = supabase.client.table("press_publication_targets")\
            .select("id, platform_type, name, base_url, is_default, is_active, created_at, updated_at, last_tested_at, test_result")\
            .eq("id", target_id)\
            .eq("company_id", company_id)\
            .maybe_single()\
            .execute()

        if not result.data:
            raise HTTPException(status_code=404, detail="Publication target not found")

        return result.data

    except HTTPException:
        raise
    except Exception as e:
        logger.error("get_publication_target_error",
            target_id=target_id,
            company_id=company_id,
            error=str(e)
        )
        raise HTTPException(status_code=500, detail="Failed to fetch publication target")


@router.put("/{target_id}")
async def update_publication_target(
    target_id: str,
    target_data: Dict[str, Any],
    company_id: str = Depends(get_company_id_from_auth)
) -> Dict[str, Any]:
    """Update publication target."""
    try:
        from utils.credential_manager import CredentialManager

        supabase = get_supabase_client()

        # Check target exists and belongs to company
        existing = supabase.client.table("press_publication_targets")\
            .select("*")\
            .eq("id", target_id)\
            .eq("company_id", company_id)\
            .maybe_single()\
            .execute()

        if not existing.data:
            raise HTTPException(status_code=404, detail="Publication target not found")

        update_data = {}

        # Handle credential update
        if 'credentials' in target_data:
            credentials_encrypted = CredentialManager.encrypt_credentials(target_data['credentials'])
            # Convert bytes to hex string for database storage
            update_data['credentials_encrypted'] = credentials_encrypted.hex()

        # Handle other field updates
        updatable_fields = ['name', 'base_url', 'is_default']
        for field in updatable_fields:
            if field in target_data:
                update_data[field] = target_data[field]

        if not update_data:
            raise HTTPException(status_code=400, detail="No valid fields to update")

        update_data['updated_at'] = datetime.utcnow().isoformat()

        result = supabase.client.table("press_publication_targets")\
            .update(update_data)\
            .eq("id", target_id)\
            .eq("company_id", company_id)\
            .execute()

        if not result.data:
            raise HTTPException(status_code=500, detail="Failed to update publication target")

        updated_target = result.data[0]

        # Remove encrypted credentials from response
        response_data = {k: v for k, v in updated_target.items() if k != 'credentials_encrypted'}

        logger.info("publication_target_updated",
            target_id=target_id,
            company_id=company_id,
            updated_fields=list(update_data.keys())
        )

        return response_data

    except HTTPException:
        raise
    except Exception as e:
        logger.error("update_publication_target_error",
            target_id=target_id,
            company_id=company_id,
            error=str(e)
        )
        raise HTTPException(status_code=500, detail="Failed to update publication target")


@router.delete("/{target_id}")
async def delete_publication_target(
    target_id: str,
    company_id: str = Depends(get_company_id_from_auth)
) -> Dict[str, Any]:
    """Soft delete (deactivate) a publication target."""
    try:
        supabase = get_supabase_client()

        result = supabase.client.table("press_publication_targets")\
            .update({"is_active": False, "updated_at": datetime.utcnow().isoformat()})\
            .eq("id", target_id)\
            .eq("company_id", company_id)\
            .execute()

        if not result.data:
            raise HTTPException(status_code=404, detail="Publication target not found")

        logger.info("publication_target_deleted",
            target_id=target_id,
            company_id=company_id
        )

        return {"success": True, "message": "Publication target deactivated"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error("delete_publication_target_error",
            target_id=target_id,
            company_id=company_id,
            error=str(e)
        )
        raise HTTPException(status_code=500, detail="Failed to delete publication target")


@router.post("/{target_id}/test")
async def test_publication_target(
    target_id: str,
    company_id: str = Depends(get_company_id_from_auth)
) -> Dict[str, Any]:
    """Test connection to a publication target."""
    try:
        from publishers.publisher_factory import PublisherFactory

        supabase = get_supabase_client()

        # Get target with credentials
        result = supabase.client.table("press_publication_targets")\
            .select("*")\
            .eq("id", target_id)\
            .eq("company_id", company_id)\
            .eq("is_active", True)\
            .maybe_single()\
            .execute()

        if not result.data:
            raise HTTPException(status_code=404, detail="Publication target not found")

        target = result.data

        # Create publisher and test
        publisher = PublisherFactory.create_publisher(
            target['platform_type'],
            target['base_url'],
            target['credentials_encrypted']
        )

        test_result = await publisher.test_connection()

        # Update test result in database
        supabase.client.table("press_publication_targets")\
            .update({
                "last_tested_at": datetime.utcnow().isoformat(),
                "test_result": test_result
            })\
            .eq("id", target_id)\
            .execute()

        logger.info("publication_target_tested",
            target_id=target_id,
            company_id=company_id,
            success=test_result.get('success')
        )

        return test_result

    except HTTPException:
        raise
    except Exception as e:
        logger.error("test_publication_target_error",
            target_id=target_id,
            company_id=company_id,
            error=str(e)
        )
        raise HTTPException(status_code=500, detail="Failed to test publication target")


@router.post("/{target_id}/verify-permissions")
async def verify_facebook_permissions(
    target_id: str,
    company_id: str = Depends(get_company_id_from_auth)
) -> Dict[str, Any]:
    """Verify Facebook API permissions by making test calls.

    This endpoint helps complete Facebook's app verification process.
    It makes API calls to test each required permission:
    - pages_manage_posts: Get page info
    - pages_read_engagement: Read page feed
    - pages_read_user_content: Read comments on posts
    - pages_manage_engagement: Verified when posting comments
    """
    try:
        from publishers.publisher_factory import PublisherFactory

        supabase = get_supabase_client()

        # Get target with credentials
        result = supabase.client.table("press_publication_targets")\
            .select("*")\
            .eq("id", target_id)\
            .eq("company_id", company_id)\
            .eq("is_active", True)\
            .maybe_single()\
            .execute()

        if not result.data:
            raise HTTPException(status_code=404, detail="Publication target not found")

        target = result.data

        if target['platform_type'] != 'facebook':
            raise HTTPException(
                status_code=400,
                detail="Permission verification is only available for Facebook targets"
            )

        # Create Facebook publisher
        publisher = PublisherFactory.create_publisher(
            target['platform_type'],
            target['base_url'],
            target['credentials_encrypted']
        )

        # Verify permissions
        verify_result = await publisher.verify_permissions()

        logger.info("facebook_permissions_verification_complete",
            target_id=target_id,
            company_id=company_id,
            results=verify_result
        )

        return {
            "target_id": target_id,
            "platform": "facebook",
            "permissions": verify_result,
            "note": "Call this endpoint to trigger API calls that verify your Facebook permissions. Check your Facebook App Dashboard to see updated verification status."
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("verify_permissions_error",
            target_id=target_id,
            company_id=company_id,
            error=str(e)
        )
        raise HTTPException(status_code=500, detail=f"Failed to verify permissions: {str(e)}")
