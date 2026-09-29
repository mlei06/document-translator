"""REST routes (``/v1``). Calls the job service and the authenticator only (ADR-003)."""

import json
import logging
import uuid
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import APIRouter, Depends, FastAPI, File, Form, Header, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from doctranslator_server.api.schemas import (
    BatchCreate,
    BatchOut,
    BatchPage,
    Capabilities,
    DocumentOut,
    DocumentPage,
    ErrorOut,
    ItemOut,
    ItemPage,
    JobOut,
    JobPage,
    Me,
    SubmitOptionsIn,
)
from doctranslator_server.auth import AuthenticationError, Authenticator, Principal
from doctranslator_server.jobs.errors import (
    AdmissionError,
    DocumentRejectedError,
    InvalidRequestError,
    ServiceError,
    TooLargeError,
)
from doctranslator_server.jobs.service import JobService, SubmitOptions
from doctranslator_server.jobs.views import FileView, SubmitResult

__all__ = ["ApiContext", "install"]

logger = logging.getLogger(__name__)

MULTIPART_OVERHEAD = 64 * 1024


@dataclass(frozen=True, slots=True)
class ApiContext:
    jobs: JobService
    auth: Authenticator
    service_version: str
    core_version: str
    max_upload_bytes: int


def _request_id(request: Request) -> str:
    return str(getattr(request.state, "request_id", "")) or str(uuid.uuid4())


def _error(
    request: Request,
    status: int,
    code: str,
    message: str,
    *,
    retryable: bool = False,
    details: dict[str, object] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body = ErrorOut(
        code=code,
        message=message,
        request_id=_request_id(request),
        retryable=retryable,
        details=details or {},
    )
    return JSONResponse(body.model_dump(), status_code=status, headers=headers)


def install(app: FastAPI, context: ApiContext) -> None:
    """Add the ``/v1`` routes, request IDs and the error envelope to ``app``."""

    @app.middleware("http")
    async def request_id(request: Request, call_next: Any) -> Response:  # pyright: ignore[reportUnusedFunction]
        request.state.request_id = str(uuid.uuid4())
        response: Response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    @app.exception_handler(ServiceError)
    async def service_error(request: Request, exc: ServiceError) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        headers = (
            {"Retry-After": str(exc.retry_after_s)} if isinstance(exc, AdmissionError) else None
        )
        details = dict(exc.details)
        if isinstance(exc, DocumentRejectedError) and exc.item_id:
            details["item_id"] = exc.item_id
        return _error(
            request,
            exc.status,
            exc.code,
            exc.message,
            retryable=exc.retryable,
            details=details,
            headers=headers,
        )

    @app.exception_handler(AuthenticationError)
    async def auth_error(request: Request, exc: AuthenticationError) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return _error(
            request,
            401,
            "unauthenticated",
            "A valid API key is required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        fields = sorted({".".join(str(p) for p in e.get("loc", ())) for e in exc.errors()})
        return _error(
            request, 422, "invalid_request", "The request is not valid.", details={"fields": fields}
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        code = {404: "not_found", 405: "method_not_allowed", 400: "bad_request"}.get(
            exc.status_code, "http_error"
        )
        return _error(request, exc.status_code, code, str(exc.detail))

    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        logger.exception("unhandled error (request %s)", _request_id(request))
        return _error(request, 500, "internal_error", "The server failed to handle the request.")

    app.state.api = context
    app.include_router(_router(context), prefix="/v1")


def _principal(
    request: Request, authorization: Annotated[str | None, Header()] = None
) -> Principal:
    context: ApiContext = request.app.state.api
    return context.auth.authenticate(authorization)


User = Annotated[Principal, Depends(_principal)]
Limit = Annotated[int, Query(ge=1, le=200)]
Cursor = Annotated[str | None, Query(max_length=200)]


def _router(ctx: ApiContext) -> APIRouter:
    router = APIRouter()
    errors: dict[int | str, dict[str, Any]] = {
        401: {"model": ErrorOut},
        404: {"model": ErrorOut},
        422: {"model": ErrorOut},
    }

    def upload_limit(content_length: Annotated[int | None, Header()] = None) -> None:
        if content_length is None:
            raise InvalidRequestError(
                "uploads need a Content-Length header", code="length_required"
            )
        if content_length > ctx.max_upload_bytes + MULTIPART_OVERHEAD:
            raise TooLargeError(f"the file is larger than {ctx.max_upload_bytes} bytes")

    def parse_options(raw: str) -> SubmitOptions:
        try:
            parsed = SubmitOptionsIn.model_validate(json.loads(raw))
        except (ValueError, ValidationError) as exc:
            raise InvalidRequestError(
                "options must be a JSON object", code="invalid_options"
            ) from exc
        return SubmitOptions(
            target=parsed.target,
            source=parsed.source,
            mode=parsed.mode,
            protected_terms=tuple(parsed.protected_terms),
            txt_encoding=parsed.txt_encoding,
            min_scale=parsed.min_scale,
            min_size_pt=parsed.min_size_pt,
            force_retranslate=parsed.force_retranslate,
        )

    def submitted(result: SubmitResult, body: JobOut | ItemOut) -> JSONResponse:
        job = result.job
        status = 200 if result.replayed else (201 if job and job.status == "succeeded" else 202)
        return JSONResponse(body.model_dump(mode="json"), status_code=status)

    def stream(view: FileView) -> FileResponse:
        return FileResponse(
            view.path,
            media_type=view.media_type,
            filename=view.filename,
            headers={"X-Content-SHA256": view.sha256},
        )

    @router.get("/health", tags=["service"])
    def health() -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
        return {"status": "ok"}

    @router.get("/me", tags=["service"], responses=errors)
    def me(user: User) -> Me:  # pyright: ignore[reportUnusedFunction]
        return Me(id=user.user_id, display_name=user.display_name, kind=user.kind)  # pyright: ignore[reportArgumentType]

    @router.get("/capabilities", tags=["service"], responses=errors)
    def capabilities(user: User) -> Capabilities:  # pyright: ignore[reportUnusedFunction]
        return Capabilities(
            **ctx.jobs.capabilities(),
            service_version=ctx.service_version,
            core_version=ctx.core_version,
        )

    @router.post("/batches", tags=["batches"], status_code=201, responses=errors)
    def create_batch(body: BatchCreate, user: User, response: Response) -> BatchOut:  # pyright: ignore[reportUnusedFunction]
        view, created = ctx.jobs.create_batch(user.user_id, str(body.idempotency_key), body.label)
        if not created:
            response.status_code = 200
        return BatchOut.of(view)

    @router.get("/batches", tags=["batches"], responses=errors)
    def list_batches(user: User, cursor: Cursor = None, limit: Limit = 50) -> BatchPage:  # pyright: ignore[reportUnusedFunction]
        page = ctx.jobs.list_batches(user.user_id, cursor, limit)
        return BatchPage(items=[BatchOut.of(b) for b in page.items], next_cursor=page.next_cursor)

    @router.get("/batches/{batch_id}", tags=["batches"], responses=errors)
    def get_batch(batch_id: str, user: User) -> BatchOut:  # pyright: ignore[reportUnusedFunction]
        return BatchOut.of(ctx.jobs.get_batch(user.user_id, batch_id))

    @router.post(
        "/batches/{batch_id}/items",
        tags=["batches"],
        status_code=202,
        response_model=ItemOut,
        responses=errors
        | {
            201: {"model": ItemOut, "description": "Completed at once from the cache"},
            409: {"model": ErrorOut},
            413: {"model": ErrorOut},
            415: {"model": ErrorOut},
            429: {"model": ErrorOut},
        },
        dependencies=[Depends(upload_limit)],
    )
    def add_item(  # pyright: ignore[reportUnusedFunction]
        batch_id: str,
        user: User,
        file: Annotated[UploadFile, File()],
        options: Annotated[str, Form(description="SubmitOptionsIn as JSON")],
        client_item_id: Annotated[uuid.UUID, Form()],
    ) -> JSONResponse:
        result = ctx.jobs.submit(
            user.user_id,
            file.filename or "document",
            file.file,
            parse_options(options),
            batch_id=batch_id,
            client_item_id=str(client_item_id),
        )
        if result.item is None:  # pragma: no cover - a batch submission always has an item
            raise RuntimeError("batch submission without an item")
        return submitted(result, ItemOut.of(result.item))

    @router.get("/batches/{batch_id}/items", tags=["batches"], responses=errors)
    def list_items(  # pyright: ignore[reportUnusedFunction]
        batch_id: str,
        user: User,
        cursor: Cursor = None,
        limit: Limit = 50,
        client_item_id: Annotated[uuid.UUID | None, Query()] = None,
    ) -> ItemPage:
        page = ctx.jobs.list_items(
            user.user_id,
            batch_id,
            cursor,
            limit,
            str(client_item_id) if client_item_id else None,
        )
        return ItemPage(items=[ItemOut.of(i) for i in page.items], next_cursor=page.next_cursor)

    @router.post("/batches/{batch_id}/seal", tags=["batches"], responses=errors)
    def seal_batch(batch_id: str, user: User) -> BatchOut:  # pyright: ignore[reportUnusedFunction]
        return BatchOut.of(ctx.jobs.seal_batch(user.user_id, batch_id))

    @router.post("/batches/{batch_id}/cancel", tags=["batches"], responses=errors)
    def cancel_batch(batch_id: str, user: User) -> BatchOut:  # pyright: ignore[reportUnusedFunction]
        return BatchOut.of(ctx.jobs.cancel_batch(user.user_id, batch_id))

    @router.post(
        "/jobs",
        tags=["jobs"],
        status_code=202,
        response_model=JobOut,
        responses=errors
        | {
            201: {"model": JobOut, "description": "Completed at once from the cache"},
            409: {"model": ErrorOut},
            413: {"model": ErrorOut},
            415: {"model": ErrorOut},
            429: {"model": ErrorOut},
        },
        dependencies=[Depends(upload_limit)],
    )
    def submit_job(  # pyright: ignore[reportUnusedFunction]
        user: User,
        file: Annotated[UploadFile, File()],
        options: Annotated[str, Form(description="SubmitOptionsIn as JSON")],
        submission_id: Annotated[uuid.UUID, Form()],
    ) -> JSONResponse:
        result = ctx.jobs.submit(
            user.user_id,
            file.filename or "document",
            file.file,
            parse_options(options),
            submission_id=str(submission_id),
        )
        if result.job is None:  # pragma: no cover - a standalone submission always has a job
            raise RuntimeError("submission without a job")
        return submitted(result, JobOut.of(result.job))

    @router.get("/jobs", tags=["jobs"], responses=errors)
    def list_jobs(  # pyright: ignore[reportUnusedFunction]
        user: User,
        cursor: Cursor = None,
        limit: Limit = 50,
        status: Annotated[
            str | None, Query(pattern="^(queued|running|succeeded|failed|cancelled)$")
        ] = None,
    ) -> JobPage:
        page = ctx.jobs.list_jobs(user.user_id, cursor, limit, status)
        return JobPage(items=[JobOut.of(j) for j in page.items], next_cursor=page.next_cursor)

    @router.get("/jobs/{job_id}", tags=["jobs"], responses=errors)
    def get_job(job_id: str, user: User) -> JobOut:  # pyright: ignore[reportUnusedFunction]
        return JobOut.of(ctx.jobs.get_job(user.user_id, job_id))

    @router.post("/jobs/{job_id}/cancel", tags=["jobs"], responses=errors)
    def cancel_job(job_id: str, user: User) -> JobOut:  # pyright: ignore[reportUnusedFunction]
        return JobOut.of(ctx.jobs.cancel_job(user.user_id, job_id))

    @router.get("/documents", tags=["documents"], responses=errors)
    def list_documents(user: User, cursor: Cursor = None, limit: Limit = 50) -> DocumentPage:  # pyright: ignore[reportUnusedFunction]
        page = ctx.jobs.list_documents(user.user_id, cursor, limit)
        return DocumentPage(
            items=[DocumentOut.of(d) for d in page.items], next_cursor=page.next_cursor
        )

    @router.get("/documents/{document_id}", tags=["documents"], responses=errors)
    def get_document(document_id: str, user: User) -> DocumentOut:  # pyright: ignore[reportUnusedFunction]
        return DocumentOut.of(ctx.jobs.get_document(user.user_id, document_id))

    @router.get(
        "/documents/{document_id}/versions/0/file",
        tags=["documents"],
        response_class=FileResponse,
        responses=errors,
    )
    def document_file(document_id: str, user: User) -> FileResponse:  # pyright: ignore[reportUnusedFunction]
        return stream(ctx.jobs.document_file(user.user_id, document_id, "output"))

    @router.get(
        "/documents/{document_id}/versions/0/fit-report",
        tags=["documents"],
        response_class=FileResponse,
        responses=errors,
    )
    def document_report(document_id: str, user: User) -> FileResponse:  # pyright: ignore[reportUnusedFunction]
        return stream(ctx.jobs.document_file(user.user_id, document_id, "report"))

    @router.get(
        "/documents/{document_id}/original",
        tags=["documents"],
        response_class=FileResponse,
        responses=errors,
    )
    def document_original(document_id: str, user: User) -> FileResponse:  # pyright: ignore[reportUnusedFunction]
        return stream(ctx.jobs.document_file(user.user_id, document_id, "original"))

    @router.delete(
        "/documents/{document_id}", tags=["documents"], status_code=204, responses=errors
    )
    def delete_document(document_id: str, user: User) -> Response:  # pyright: ignore[reportUnusedFunction]
        ctx.jobs.delete_document(user.user_id, document_id)
        return Response(status_code=204)

    return router
