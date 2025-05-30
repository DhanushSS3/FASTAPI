# app/api/v1/endpoints/money_requests.py

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional

from app.database.session import get_db
from app.database.models import User # MoneyRequest model is used via CRUD
from app.schemas.money_request import (
    MoneyRequestCreate, # Used by user-facing endpoints (in users.py)
    MoneyRequestResponse,
    MoneyRequestUpdateStatus
)
# from app.schemas.user import StatusResponse # General status response, if needed

from app.crud import money_request as crud_money_request
from app.core.security import get_current_user, get_current_admin_user # User auth

import logging

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/money-requests",
    tags=["Money Requests"] # MODIFICATION HERE: Changed to "Money Requests"
)

# User-facing endpoints to create and view their requests are now in users.py (e.g. /wallet/deposit)
# This router will now focus on admin management of money requests.


# --- Admin Endpoints ---

@router.patch(
    "/{request_id}/status", # Path relative to the router's prefix
    response_model=MoneyRequestResponse,
    summary="Update Money Request Status (Admin)",
    description="Allows an admin to approve (1), reject (2), or set to pending (0) a money request. Approving a request updates the user's wallet balance and creates a wallet transaction record.",
    dependencies=[Depends(get_current_admin_user)] # Ensures only admins can access
)
async def admin_update_money_request_status(
    request_id: int,
    status_update: MoneyRequestUpdateStatus, # Contains the new status
    current_admin: User = Depends(get_current_admin_user), # Get admin for logging
    db: AsyncSession = Depends(get_db)
):
    """
    Admin endpoint to change the status of a money request.
    - Status 0: Requested/Pending
    - Status 1: Approved (triggers wallet update and wallet record creation)
    - Status 2: Rejected
    """
    # Pydantic already validates status_update.status is 0, 1, or 2 based on schema
    
    try:
        updated_request = await crud_money_request.update_money_request_status(
            db=db,
            request_id=request_id,
            new_status=status_update.status,
            admin_id=current_admin.id
        )

        if updated_request is None:
            # This scenario implies the request was not found OR it was already processed and not in a state to be updated.
            # The CRUD function logs specifics. We check the DB state to provide a more accurate HTTP error.
            db_request_check = await crud_money_request.get_money_request_by_id(db, request_id)
            if not db_request_check:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Money request with ID {request_id} not found."
                )
            # If it exists but update_money_request_status returned None, it means it was already processed
            # and its status was not 0.
            if db_request_check.status != 0:
                 raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Money request ID {request_id} has already been processed (current status: {db_request_check.status}) or is not in a pending state. Cannot update to {status_update.status}."
                )
            # Fallback for other unexpected None returns from CRUD
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to update money request ID {request_id}. Please check logs."
            )
            
        logger.info(f"Admin {current_admin.email} (ID: {current_admin.id}) successfully updated money request ID {request_id} to status {updated_request.status}.")
        return updated_request
        
    except ValueError as ve: # Catches insufficient funds or other validation errors from wallet processing
        logger.warning(f"Admin (ID: {current_admin.id}) failed to approve/process money request ID {request_id} due to: {ve}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail=str(ve) # Provide the specific error message (e.g., "Insufficient funds...")
        )
    except Exception as e:
        logger.error(f"Admin (ID: {current_admin.id}) encountered an error updating status for money request ID {request_id}: {e}", exc_info=True)
        # The CRUD layer's transaction should handle rollback.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while updating the money request status. The operation has been rolled back."
        )

@router.get(
    "/", # Lists all requests, path relative to router's prefix
    response_model=List[MoneyRequestResponse],
    summary="List All Money Requests (Admin)",
    description="Allows an admin to view all money requests, with optional filtering by status.",
    dependencies=[Depends(get_current_admin_user)] # Ensures only admins can access
)
async def admin_get_all_money_requests(
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(100, ge=1, le=200, description="Maximum number of records to return"),
    status_filter: Optional[int] = Query(None, alias="status", ge=0, le=2, description="Filter by status: 0 (requested), 1 (approved), 2 (rejected)"),
    user_id_filter: Optional[int] = Query(None, alias="user_id", description="Filter by User ID"), # Added User ID filter
    db: AsyncSession = Depends(get_db)
    # current_admin: User = Depends(get_current_admin_user) # Not strictly needed if only using for auth
):
    """
    Admin endpoint to list all money requests with pagination and optional filters.
    """
    # Modify crud_money_request.get_all_money_requests if user_id_filter is to be implemented at DB level
    # For now, assuming get_all_money_requests might be enhanced or filtering done post-fetch if simple.
    # If user_id_filter is added to CRUD:
    # requests = await crud_money_request.get_all_money_requests(
    #     db=db, skip=skip, limit=limit, status=status_filter, user_id=user_id_filter
    # )
    
    # Assuming current get_all_money_requests only filters by status at DB level:
    requests = await crud_money_request.get_all_money_requests(
        db=db, skip=skip, limit=limit, status=status_filter
    )
    if user_id_filter is not None: # Post-fetch filtering if not in CRUD
        requests = [req for req in requests if req.user_id == user_id_filter]
        
    return requests

@router.get(
    "/{request_id}", # Get a specific request by ID
    response_model=MoneyRequestResponse,
    summary="Get Specific Money Request (Admin)",
    description="Allows an admin to view the details of a specific money request by its ID.",
    dependencies=[Depends(get_current_admin_user)] # Ensures only admins can access
)
async def admin_get_money_request_by_id(
    request_id: int,
    db: AsyncSession = Depends(get_db)
):
    db_request = await crud_money_request.get_money_request_by_id(db, request_id=request_id)
    if db_request is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Money request with ID {request_id} not found."
        )
    return db_request

