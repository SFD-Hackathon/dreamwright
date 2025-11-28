"""Image generation routes."""

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status

from dreamwright_core_schemas import Panel
from dreamwright_services import ImageService
from dreamwright_services.exceptions import DependencyError, NotFoundError
from dreamwright_services.job import get_job_service
from dreamwright_api.deps import get_project_manager, verify_token
from dreamwright_api.schemas import (
    DependencyErrorResponse,
    ErrorResponse,
    GenerateImageRequest,
    ImageGenerationResult,
    JobResponse,
    PaginatedResponse,
    PaginationMeta,
)

router = APIRouter(prefix="/projects/{project_id}", tags=["Images"])


@router.get(
    "/chapters/{chapter_number}/panels",
    response_model=PaginatedResponse[Panel],
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def list_panels(
    project_id: str,
    chapter_number: int = Path(..., ge=1, description="Chapter number"),
    token: Annotated[Optional[str], Depends(verify_token)] = None,
    scene_number: Optional[int] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """List panels for a chapter (with their image paths)."""
    manager = get_project_manager(project_id)
    service = ImageService(manager)

    try:
        service.get_chapter(chapter_number)
    except NotFoundError:
        raise HTTPException(status_code=404, detail=f"Chapter {chapter_number} not found")

    panels, total = service.list_panels(
        chapter_number=chapter_number,
        scene_number=scene_number,
        limit=limit,
        offset=offset,
    )

    return PaginatedResponse(
        data=panels,
        pagination=PaginationMeta(
            total=total,
            limit=limit,
            offset=offset,
            has_more=offset + limit < total,
        ),
    )


# Chapter-level image generation
@router.post(
    "/chapters/{chapter_number}/images",
    response_model=JobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": DependencyErrorResponse},
    },
)
async def generate_chapter_images(
    project_id: str,
    chapter_number: int = Path(..., ge=1, description="Chapter number"),
    request: GenerateImageRequest = GenerateImageRequest(),
    token: Annotated[Optional[str], Depends(verify_token)] = None,
):
    """Generate all panel images for a chapter.

    Dependencies:
    - Chapter script must exist
    - All characters in panels must have portrait/reference assets
    - All locations in scenes must have reference assets

    This is an async operation.
    """
    manager = get_project_manager(project_id)
    service = ImageService(manager)

    try:
        service.get_chapter(chapter_number)
    except NotFoundError:
        raise HTTPException(status_code=404, detail=f"Chapter {chapter_number} not found")

    # Validate dependencies
    missing = service.validate_dependencies(chapter_number)
    if missing:
        raise HTTPException(
            status_code=409,
            detail={
                "error": {
                    "code": "DEPENDENCY_ERROR",
                    "message": f"Cannot generate images for chapter {chapter_number}: dependencies not met",
                },
                "missing_dependencies": missing,
            },
        )

    # Create job
    job_service = get_job_service()
    job = job_service.create_job(
        "image_generation",
        metadata={
            "project_id": project_id,
            "chapter_number": chapter_number,
            "style": request.style,
            "overwrite": request.overwrite,
        },
    )

    # Start async generation
    async def generate():
        result = await service.generate_panels(
            chapter_number=chapter_number,
            style=request.style,
            overwrite=request.overwrite,
        )
        return ImageGenerationResult(
            chapter_number=chapter_number,
            generated_count=result["generated_count"],
            skipped_count=result["skipped_count"],
            error_count=result["error_count"],
            output_dir=result.get("output_dir"),
        ).model_dump()

    job_service.start_job(job, generate())

    return JobResponse(
        job_id=job.id,
        type=job.type,
        status=job.status.value,
        created_at=job.created_at,
        metadata=job.metadata,
    )


# Scene-level image generation
@router.post(
    "/chapters/{chapter_number}/scenes/{scene_number}/images",
    response_model=JobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": DependencyErrorResponse},
    },
)
async def generate_scene_images(
    project_id: str,
    chapter_number: int = Path(..., ge=1, description="Chapter number"),
    scene_number: int = Path(..., ge=1, description="Scene number"),
    request: GenerateImageRequest = GenerateImageRequest(),
    token: Annotated[Optional[str], Depends(verify_token)] = None,
):
    """Generate all panel images for a specific scene.

    This is an async operation.
    """
    manager = get_project_manager(project_id)
    service = ImageService(manager)

    try:
        service.get_chapter(chapter_number)
    except NotFoundError:
        raise HTTPException(status_code=404, detail=f"Chapter {chapter_number} not found")

    # Validate dependencies
    missing = service.validate_dependencies(chapter_number, scene_number)
    if missing:
        raise HTTPException(
            status_code=409,
            detail={
                "error": {
                    "code": "DEPENDENCY_ERROR",
                    "message": f"Cannot generate images for scene {scene_number}: dependencies not met",
                },
                "missing_dependencies": missing,
            },
        )

    # Create job
    job_service = get_job_service()
    job = job_service.create_job(
        "scene_image_generation",
        metadata={
            "project_id": project_id,
            "chapter_number": chapter_number,
            "scene_number": scene_number,
            "style": request.style,
            "overwrite": request.overwrite,
        },
    )

    # Start async generation
    async def generate():
        result = await service.generate_panels(
            chapter_number=chapter_number,
            scene_number=scene_number,
            style=request.style,
            overwrite=request.overwrite,
        )
        return ImageGenerationResult(
            chapter_number=chapter_number,
            scene_number=scene_number,
            generated_count=result["generated_count"],
            skipped_count=result["skipped_count"],
            error_count=result["error_count"],
        ).model_dump()

    job_service.start_job(job, generate())

    return JobResponse(
        job_id=job.id,
        type=job.type,
        status=job.status.value,
        created_at=job.created_at,
        metadata=job.metadata,
    )


# Single panel image generation
@router.post(
    "/chapters/{chapter_number}/scenes/{scene_number}/panels/{panel_number}/image",
    response_model=JobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": DependencyErrorResponse},
    },
)
async def generate_panel_image(
    project_id: str,
    chapter_number: int = Path(..., ge=1, description="Chapter number"),
    scene_number: int = Path(..., ge=1, description="Scene number"),
    panel_number: int = Path(..., ge=1, description="Panel number"),
    request: GenerateImageRequest = GenerateImageRequest(),
    token: Annotated[Optional[str], Depends(verify_token)] = None,
):
    """Generate or regenerate a single panel image.

    Use overwrite=true to regenerate an existing panel image.

    This is an async operation.
    """
    manager = get_project_manager(project_id)
    service = ImageService(manager)

    try:
        service.get_panel(chapter_number, scene_number, panel_number)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    # Create job
    job_service = get_job_service()
    job = job_service.create_job(
        "panel_image_generation",
        metadata={
            "project_id": project_id,
            "chapter_number": chapter_number,
            "scene_number": scene_number,
            "panel_number": panel_number,
            "style": request.style,
            "overwrite": request.overwrite,
        },
    )

    # Start async generation
    async def generate():
        result = await service.generate_single_panel(
            chapter_number=chapter_number,
            scene_number=scene_number,
            panel_number=panel_number,
            style=request.style,
            overwrite=request.overwrite,
        )
        return ImageGenerationResult(
            chapter_number=chapter_number,
            scene_number=scene_number,
            panel_number=panel_number,
            generated_count=0 if result.skipped else 1,
            skipped_count=1 if result.skipped else 0,
            error_count=1 if result.error else 0,
        ).model_dump()

    job_service.start_job(job, generate())

    return JobResponse(
        job_id=job.id,
        type=job.type,
        status=job.status.value,
        created_at=job.created_at,
        metadata=job.metadata,
    )
