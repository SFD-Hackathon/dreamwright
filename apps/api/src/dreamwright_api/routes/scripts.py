"""Script generation routes."""

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status

from dreamwright_core_schemas import Chapter, Scene, Panel
from dreamwright_services import ScriptService
from dreamwright_services.exceptions import DependencyError, NotFoundError, ValidationError
from dreamwright_services.job import get_job_service
from dreamwright_api.deps import get_project_manager, verify_token
from dreamwright_api.schemas import (
    DependencyErrorResponse,
    ErrorResponse,
    GenerateScriptRequest,
    JobResponse,
    PaginatedResponse,
    PaginationMeta,
    ScriptGenerationResult,
)

router = APIRouter(prefix="/projects/{project_id}", tags=["Scripts"])


# Chapter-level endpoints
@router.get(
    "/chapters",
    response_model=PaginatedResponse[Chapter],
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def list_chapters(
    project_id: str,
    token: Annotated[Optional[str], Depends(verify_token)] = None,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """List all chapters."""
    manager = get_project_manager(project_id)
    service = ScriptService(manager)

    chapters, total = service.list_chapters(limit=limit, offset=offset)

    return PaginatedResponse(
        data=chapters,
        pagination=PaginationMeta(
            total=total,
            limit=limit,
            offset=offset,
            has_more=offset + limit < total,
        ),
    )


@router.get(
    "/chapters/{chapter_number}",
    response_model=Chapter,
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def get_chapter(
    project_id: str,
    chapter_number: int = Path(..., ge=1),
    token: Annotated[Optional[str], Depends(verify_token)] = None,
):
    """Get chapter details."""
    manager = get_project_manager(project_id)
    service = ScriptService(manager)

    try:
        return service.get_chapter(chapter_number)
    except NotFoundError:
        raise HTTPException(status_code=404, detail=f"Chapter {chapter_number} not found")


@router.delete(
    "/chapters/{chapter_number}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def delete_chapter(
    project_id: str,
    chapter_number: int = Path(..., ge=1),
    token: Annotated[Optional[str], Depends(verify_token)] = None,
):
    """Delete chapter."""
    manager = get_project_manager(project_id)
    service = ScriptService(manager)

    if not service.delete_chapter(chapter_number):
        raise HTTPException(status_code=404, detail=f"Chapter {chapter_number} not found")


@router.post(
    "/chapters/{chapter_number}/script",
    response_model=JobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": DependencyErrorResponse},
    },
)
async def generate_chapter_script(
    project_id: str,
    chapter_number: int = Path(..., ge=1, description="Chapter/beat number to generate"),
    request: GenerateScriptRequest = GenerateScriptRequest(),
    token: Annotated[Optional[str], Depends(verify_token)] = None,
):
    """Generate or regenerate chapter script from story beat.

    Chapter N requires Chapter N-1 to exist for story continuity.
    Include feedback to guide regeneration.
    This is an async operation.
    """
    manager = get_project_manager(project_id)
    service = ScriptService(manager)

    # Validate beat number
    try:
        service.get_beat(chapter_number)
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Validate dependencies
    missing = service.validate_chapter_dependencies(chapter_number)
    if missing:
        raise HTTPException(
            status_code=409,
            detail={
                "error": {
                    "code": "DEPENDENCY_ERROR",
                    "message": f"Cannot generate chapter {chapter_number}: dependencies not met",
                },
                "missing_dependencies": missing,
            },
        )

    # Create job
    job_service = get_job_service()
    job = job_service.create_job(
        "script_generation",
        metadata={
            "project_id": project_id,
            "chapter_number": chapter_number,
            "panels_per_scene": request.panels_per_scene,
            "has_feedback": request.feedback is not None,
        },
    )

    # Start async generation
    async def generate():
        chapter = await service.generate_chapter(
            beat_number=chapter_number,
            panels_per_scene=request.panels_per_scene,
            feedback=request.feedback,
        )
        return ScriptGenerationResult(
            chapter_number=chapter.number,
            scene_count=len(chapter.scenes),
            panel_count=sum(len(s.panels) for s in chapter.scenes),
        ).model_dump()

    job_service.start_job(job, generate())

    return JobResponse(
        job_id=job.id,
        type=job.type,
        status=job.status.value,
        created_at=job.created_at,
        metadata=job.metadata,
    )


# Scene-level endpoints
@router.get(
    "/chapters/{chapter_number}/scenes/{scene_number}",
    response_model=Scene,
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def get_scene(
    project_id: str,
    chapter_number: int = Path(..., ge=1),
    scene_number: int = Path(..., ge=1),
    token: Annotated[Optional[str], Depends(verify_token)] = None,
):
    """Get scene details."""
    manager = get_project_manager(project_id)
    service = ScriptService(manager)

    try:
        return service.get_scene(chapter_number, scene_number)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post(
    "/chapters/{chapter_number}/scenes/{scene_number}/script",
    response_model=JobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
    },
)
async def regenerate_scene_script(
    project_id: str,
    chapter_number: int = Path(..., ge=1),
    scene_number: int = Path(..., ge=1),
    request: GenerateScriptRequest = GenerateScriptRequest(),
    token: Annotated[Optional[str], Depends(verify_token)] = None,
):
    """Regenerate scene script with optional feedback.

    Use feedback to guide the regeneration, e.g.:
    - "Include more dialogue between characters"
    - "Make the scene more dramatic"
    - "Add a confrontation between Kai and the villain"

    This is an async operation.
    """
    manager = get_project_manager(project_id)
    service = ScriptService(manager)

    # Validate chapter exists
    try:
        service.get_chapter(chapter_number)
    except NotFoundError:
        raise HTTPException(status_code=404, detail=f"Chapter {chapter_number} not found")

    # Create job
    job_service = get_job_service()
    job = job_service.create_job(
        "scene_script_regeneration",
        metadata={
            "project_id": project_id,
            "chapter_number": chapter_number,
            "scene_number": scene_number,
            "has_feedback": request.feedback is not None,
        },
    )

    # Start async generation
    async def generate():
        scene = await service.regenerate_scene(
            chapter_number=chapter_number,
            scene_number=scene_number,
            panels_per_scene=request.panels_per_scene,
            feedback=request.feedback,
        )
        return ScriptGenerationResult(
            chapter_number=chapter_number,
            scene_number=scene.number,
            panel_count=len(scene.panels),
        ).model_dump()

    job_service.start_job(job, generate())

    return JobResponse(
        job_id=job.id,
        type=job.type,
        status=job.status.value,
        created_at=job.created_at,
        metadata=job.metadata,
    )


# Panel-level endpoints
@router.get(
    "/chapters/{chapter_number}/scenes/{scene_number}/panels/{panel_number}",
    response_model=Panel,
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def get_panel(
    project_id: str,
    chapter_number: int = Path(..., ge=1),
    scene_number: int = Path(..., ge=1),
    panel_number: int = Path(..., ge=1),
    token: Annotated[Optional[str], Depends(verify_token)] = None,
):
    """Get panel details."""
    manager = get_project_manager(project_id)
    service = ScriptService(manager)

    try:
        return service.get_panel(chapter_number, scene_number, panel_number)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post(
    "/chapters/{chapter_number}/scenes/{scene_number}/panels/{panel_number}/script",
    response_model=JobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
    },
)
async def regenerate_panel_script(
    project_id: str,
    chapter_number: int = Path(..., ge=1),
    scene_number: int = Path(..., ge=1),
    panel_number: int = Path(..., ge=1),
    request: GenerateScriptRequest = GenerateScriptRequest(),
    token: Annotated[Optional[str], Depends(verify_token)] = None,
):
    """Regenerate panel script with optional feedback.

    Use feedback to guide the regeneration, e.g.:
    - "Include both characters in the panel"
    - "Change the camera angle to close-up"
    - "Add dialogue for Mina"

    This is an async operation.
    """
    manager = get_project_manager(project_id)
    service = ScriptService(manager)

    # Validate scene exists
    try:
        service.get_scene(chapter_number, scene_number)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    # Create job
    job_service = get_job_service()
    job = job_service.create_job(
        "panel_script_regeneration",
        metadata={
            "project_id": project_id,
            "chapter_number": chapter_number,
            "scene_number": scene_number,
            "panel_number": panel_number,
            "has_feedback": request.feedback is not None,
        },
    )

    # Start async generation
    async def generate():
        panel = await service.regenerate_panel(
            chapter_number=chapter_number,
            scene_number=scene_number,
            panel_number=panel_number,
            feedback=request.feedback,
        )
        return ScriptGenerationResult(
            chapter_number=chapter_number,
            scene_number=scene_number,
            panel_number=panel.number,
        ).model_dump()

    job_service.start_job(job, generate())

    return JobResponse(
        job_id=job.id,
        type=job.type,
        status=job.status.value,
        created_at=job.created_at,
        metadata=job.metadata,
    )
