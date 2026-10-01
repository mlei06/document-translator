"""REST routes (``/v1``) and the built web UI. Calls the job service and the authenticator only
(ADR-003). Storage semantics follow ADR-014; browser sessions and UI extensions ADR-017."""

import json
import logging
import threading
import time
import uuid
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    Query,
    Request,
    UploadFile,
)
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import ValidationError
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from doctranslator_server.api.schemas import (
    AccountCreate,
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
    SessionCreate,
    SessionOut,
    SubmitOptionsIn,
    TranslateIn,
    TranslationSettingsIn,
    TranslationSettingsOut,
)
from doctranslator_server.auth import (
    AuthenticationError,
    Authenticator,
    CsrfError,
    NewSession,
    Principal,
)
from doctranslator_server.jobs.errors import (
    AdmissionError,
    DocumentRejectedError,
    InvalidRequestError,
    NotFoundError,
    ServiceError,
    TooLargeError,
    UnavailableError,
)
from doctranslator_server.jobs.service import JobService, SubmitOptions
from doctranslator_server.jobs.views import FileView, SubmitResult

__all__ = ["SESSION_COOKIE", "ApiContext", "install"]

logger = logging.getLogger(__name__)

MULTIPART_OVERHEAD = 64 * 1024
SESSION_COOKIE = "dt_session"
_SIGN_IN_LIMIT = 10
_SIGN_IN_WINDOW_S = 300.0


@dataclass
class _Limiter:
    """Failed sign-ins per client address in a sliding window (ADR-017; per web process)."""

    limit: int = _SIGN_IN_LIMIT
    window: float = _SIGN_IN_WINDOW_S
    _failures: dict[str, deque[float]] = field(default_factory=dict[str, deque[float]])
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def admit(self, client: str) -> bool:
        now = time.monotonic()
        with self._lock:
            for key in list(self._failures):
                values = self._failures[key]
                while values and now - values[0] > self.window:
                    values.popleft()
                if not values:
                    del self._failures[key]
            if client not in self._failures and len(self._failures) >= 10000:
                return False
            attempts = self._failures.setdefault(client, deque())
            if len(attempts) >= self.limit:
                return False
            attempts.append(now)
            return True


@dataclass(frozen=True, slots=True)
class ApiContext:
    jobs: JobService
    auth: Authenticator
    service_version: str
    core_version: str
    max_upload_bytes: int
    web_dir: Path | None = None
    registration_enabled: bool = False
    limiter: _Limiter = field(default_factory=_Limiter)


@dataclass(frozen=True, slots=True)
class Caller:
    principal: Principal
    session_id: str | None


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


def _own_origin(request: Request) -> str:
    return f"{request.url.scheme}://{request.url.netloc}"


def _caller(
    request: Request,
    authorization: Annotated[str | None, Header(include_in_schema=False)] = None,
    x_csrf_token: Annotated[str | None, Header(include_in_schema=False)] = None,
    origin: Annotated[str | None, Header(include_in_schema=False)] = None,
) -> Caller:
    """Bearer key or session cookie; both present must name the same owner (ADR-017)."""
    context: ApiContext = request.app.state.api
    cookie = request.cookies.get(SESSION_COOKIE)
    bearer = context.auth.authenticate(authorization) if authorization else None
    session: tuple[Principal, str] | None = None
    if cookie:
        try:
            session = context.auth.from_session(
                cookie,
                method=request.method,
                csrf=x_csrf_token,
                origin=origin,
                own_origin=_own_origin(request),
            )
        except AuthenticationError:
            if bearer is None:
                raise
            session = None  # a stale cookie next to a valid key: the key authenticates
    if bearer is not None and session is not None and bearer.user_id != session[0].user_id:
        raise AuthenticationError
    if bearer is not None:
        return Caller(bearer, None)
    if session is not None:
        return Caller(session[0], session[1])
    raise AuthenticationError


User = Annotated[Caller, Depends(_caller)]
Limit = Annotated[int, Query(ge=1, le=200)]
Cursor = Annotated[str | None, Query(max_length=200)]
Search = Annotated[str | None, Query(max_length=200)]


class _UploadAdmission:
    """Reserve and authenticate before multipart parsing writes any request body."""

    def __init__(self, app: ASGIApp, context: ApiContext) -> None:
        self.app, self.context = app, context

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") != "POST":
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        if not request.headers.get("content-type", "").startswith("multipart/form-data"):
            await self.app(scope, receive, send)
            return
        limit = self.context.max_upload_bytes + MULTIPART_OVERHEAD
        try:
            declared = int(request.headers.get("content-length", str(limit)))
            if declared < 0 or declared > limit:
                raise TooLargeError("upload exceeds the request size limit")
            caller = await run_in_threadpool(
                _caller,
                request,
                request.headers.get("authorization"),
                request.headers.get("x-csrf-token"),
                request.headers.get("origin"),
            )
            reservation = await run_in_threadpool(
                self.context.jobs.reserve_upload, caller.principal.user_id, declared
            )
        except AuthenticationError:
            await _error(request, 401, "unauthenticated", "Sign in again, or use a valid API key.")(
                scope, receive, send
            )
            return
        except CsrfError:
            await _error(
                request, 403, "csrf_failed", "The request was not sent by this application."
            )(scope, receive, send)
            return
        except ValueError:
            await _error(request, 400, "bad_request", "invalid Content-Length")(
                scope, receive, send
            )
            return
        except ServiceError as exc:
            await _error(
                request,
                exc.status,
                exc.code,
                exc.message,
                retryable=exc.retryable,
                headers={"Retry-After": "5"} if exc.retryable else None,
            )(scope, receive, send)
            return
        received = 0

        async def bounded_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > declared:
                    raise TooLargeError("upload exceeds its reserved request size")
            return message

        try:
            await self.app(scope, bounded_receive, send)
        finally:
            await run_in_threadpool(self.context.jobs.release_upload, reservation)


def install(app: FastAPI, context: ApiContext) -> None:
    """Add ``/v1``, request IDs, security headers, the error envelope and (if built) the web UI."""
    app.add_middleware(_UploadAdmission, context=context)

    @app.middleware("http")
    async def request_id(  # pyright: ignore[reportUnusedFunction]
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request.state.request_id = str(uuid.uuid4())
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        if not request.url.path.startswith("/v1/docs"):
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; img-src 'self' blob: data:; style-src 'self' 'unsafe-inline'; "
                "font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'"
            )
        return response

    @app.exception_handler(ServiceError)
    async def service_error(request: Request, exc: ServiceError) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        headers = (
            {"Retry-After": str(exc.retry_after_s)}
            if isinstance(exc, (AdmissionError, UnavailableError))
            else None
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
            "Sign in again, or use a valid API key.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    @app.exception_handler(CsrfError)
    async def csrf_error(request: Request, exc: CsrfError) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return _error(request, 403, "csrf_failed", "The request was not sent by this application.")

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
    if context.web_dir is not None:
        _serve_web(app, context.web_dir)


def _serve_web(app: FastAPI, root: Path) -> None:
    """The built SPA: real files when they exist, else ``index.html`` (never for ``/v1``)."""
    root = root.resolve()
    index = root / "index.html"

    @app.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    def web(path: str) -> Response:  # pyright: ignore[reportUnusedFunction]
        if path == "v1" or path.startswith("v1/"):
            raise StarletteHTTPException(404, "not found")
        candidate = (root / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(root):
            cache = (
                "public, max-age=31536000, immutable"
                if candidate.parent.name == "assets"
                else "no-cache"
            )
            return FileResponse(candidate, headers={"Cache-Control": cache})
        return FileResponse(index, headers={"Cache-Control": "no-cache"})


def _options(parsed: SubmitOptionsIn) -> SubmitOptions:
    return SubmitOptions(
        target=parsed.target,
        source=parsed.source,
        mode=parsed.mode,
        translator_id=parsed.translator_id,
        protected_terms=tuple(parsed.protected_terms),
        use_default_dictionary=parsed.use_default_dictionary,
        txt_encoding=parsed.txt_encoding,
        min_scale=parsed.min_scale,
        min_size_pt=parsed.min_size_pt,
        fit=parsed.fit.model_dump(),
        force_retranslate=parsed.force_retranslate,
        retention=parsed.retention,
        selection_policy=parsed.selection_policy,
        download_semantics=parsed.download_semantics,
    )


def _parse_options(raw: str) -> SubmitOptions:
    try:
        return _options(SubmitOptionsIn.model_validate(json.loads(raw)))
    except (ValueError, ValidationError) as exc:
        raise InvalidRequestError("options must be a JSON object", code="invalid_options") from exc


def _submitted(result: SubmitResult, body: JobOut | ItemOut) -> JSONResponse:
    job = result.job
    status = 200 if result.replayed else (201 if job and job.status == "succeeded" else 202)
    return JSONResponse(body.model_dump(mode="json"), status_code=status)


def _stream(view: FileView) -> FileResponse:
    return FileResponse(
        view.path,
        media_type=view.media_type,
        filename=view.filename,
        headers={"X-Content-SHA256": view.sha256, "Cache-Control": "private, no-store"},
        background=BackgroundTask(view.on_complete) if view.on_complete else None,
    )


def _router(ctx: ApiContext) -> APIRouter:
    router = APIRouter()
    errors: dict[int | str, dict[str, Any]] = {
        401: {"model": ErrorOut},
        404: {"model": ErrorOut},
        422: {"model": ErrorOut},
    }
    submit_errors = errors | {
        201: {"description": "Completed at once with the document's current translation"},
        409: {"model": ErrorOut},
        413: {"model": ErrorOut},
        415: {"model": ErrorOut},
        429: {"model": ErrorOut},
    }

    def upload_limit(
        content_length: Annotated[int | None, Header(include_in_schema=False)] = None,
    ) -> None:
        if content_length is None:
            raise InvalidRequestError(
                "uploads need a Content-Length header", code="length_required"
            )
        if content_length > ctx.max_upload_bytes + MULTIPART_OVERHEAD:
            raise TooLargeError(f"the file is larger than {ctx.max_upload_bytes} bytes")

    def me_of(principal: Principal) -> Me:
        storage = ctx.jobs.storage(principal.user_id)
        return Me(
            id=principal.user_id,
            display_name=principal.display_name,
            kind=principal.kind,  # pyright: ignore[reportArgumentType]
            storage_used_bytes=storage["used_bytes"],
            storage_quota_bytes=storage["quota_bytes"],
        )

    # Service and sessions

    @router.get("/health", tags=["service"])
    def health() -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
        return {"status": "ok"}

    def set_session_cookie(session: NewSession, request: Request, response: Response) -> SessionOut:
        response.set_cookie(
            SESSION_COOKIE,
            session.token,
            httponly=True,
            secure=request.url.scheme == "https",
            samesite="strict",
            path="/",
            max_age=int(session.expires_at.timestamp() - time.time()),
        )
        return SessionOut(
            user=me_of(session.principal), csrf_token=session.csrf, expires_at=session.expires_at
        )

    @router.post("/accounts", tags=["sessions"], status_code=201, responses=errors)
    def register(  # pyright: ignore[reportUnusedFunction]
        body: AccountCreate,
        request: Request,
        response: Response,
        origin: Annotated[str | None, Header(include_in_schema=False)] = None,
    ) -> SessionOut:
        if not ctx.registration_enabled:
            raise NotFoundError("account registration")
        if origin is not None and origin.rstrip("/") != _own_origin(request):
            raise CsrfError
        client = "register:" + (request.client.host if request.client else "unknown")
        if not ctx.limiter.admit(client):
            raise AdmissionError("too many account requests; try later", code="rate_limited")
        session = ctx.auth.register(body.email, body.password.get_secret_value(), body.display_name)
        return set_session_cookie(session, request, response)

    @router.post(
        "/sessions",
        tags=["sessions"],
        status_code=201,
        responses={401: {"model": ErrorOut}, 403: {"model": ErrorOut}, 429: {"model": ErrorOut}},
    )
    def sign_in(  # pyright: ignore[reportUnusedFunction]
        body: SessionCreate,
        request: Request,
        response: Response,
        origin: Annotated[str | None, Header(include_in_schema=False)] = None,
    ) -> SessionOut:
        """Exchange an API key for a browser session (HttpOnly cookie plus CSRF token)."""
        if origin is not None and origin.rstrip("/") != _own_origin(request):
            raise CsrfError
        client = request.client.host if request.client else "unknown"
        if not ctx.limiter.admit(client):
            raise AdmissionError(
                "too many failed sign-ins; wait a few minutes", code="rate_limited"
            )
        if body.key is not None:
            session = ctx.auth.start_session(body.key.get_secret_value())
        else:
            if body.email is None or body.password is None:
                raise AuthenticationError
            session = ctx.auth.password_session(body.email, body.password.get_secret_value())
        return set_session_cookie(session, request, response)

    @router.get("/sessions/current", tags=["sessions"], responses=errors)
    def current_session(user: User, request: Request) -> SessionOut:  # pyright: ignore[reportUnusedFunction]
        """The signed-in browser session with its CSRF token, for a reloaded or new tab."""
        cookie = request.cookies.get(SESSION_COOKIE)
        if user.session_id is None or cookie is None:
            raise NotFoundError("no browser session; sign in with POST /v1/sessions")
        csrf, expires_at = ctx.auth.session_csrf(cookie)
        return SessionOut(user=me_of(user.principal), csrf_token=csrf, expires_at=expires_at)

    @router.delete("/sessions/current", tags=["sessions"], status_code=204, responses=errors)
    def sign_out(user: User) -> Response:  # pyright: ignore[reportUnusedFunction]
        if user.session_id is not None:
            ctx.auth.end_session(user.session_id)
        response = Response(status_code=204)
        response.delete_cookie(SESSION_COOKIE, path="/")
        return response

    @router.get("/me", tags=["service"], responses=errors)
    def me(user: User) -> Me:  # pyright: ignore[reportUnusedFunction]
        return me_of(user.principal)

    @router.get("/me/translation-settings", tags=["service"], responses=errors)
    def translation_settings(user: User) -> TranslationSettingsOut:  # pyright: ignore[reportUnusedFunction]
        return TranslationSettingsOut(**ctx.jobs.translation_settings(user.principal.user_id))

    @router.put("/me/translation-settings", tags=["service"], responses=errors)
    def update_translation_settings(
        user: User, body: TranslationSettingsIn
    ) -> TranslationSettingsOut:  # pyright: ignore[reportUnusedFunction]
        return TranslationSettingsOut(
            **ctx.jobs.update_translation_settings(
                user.principal.user_id, tuple(body.protected_terms), body.use_default_dictionary
            )
        )

    @router.get("/capabilities", tags=["service"], responses=errors)
    def capabilities(user: User) -> Capabilities:  # pyright: ignore[reportUnusedFunction]
        return Capabilities(
            **ctx.jobs.capabilities(),
            service_version=ctx.service_version,
            core_version=ctx.core_version,
        )

    @router.post("/translators/refresh", tags=["service"], responses=errors)
    def refresh_translators(user: User) -> Capabilities:  # pyright: ignore[reportUnusedFunction]
        return Capabilities(
            **ctx.jobs.capabilities(refresh=True),
            service_version=ctx.service_version,
            core_version=ctx.core_version,
        )

    # Saved documents (ADR-014)

    @router.post(
        "/documents",
        tags=["documents"],
        status_code=201,
        responses=submit_errors | {200: {"description": "The owner's existing document"}},
        dependencies=[Depends(upload_limit)],
    )
    def create_document(  # pyright: ignore[reportUnusedFunction]
        user: User,
        response: Response,
        file: Annotated[UploadFile, File()],
        new_document: Annotated[bool, Form()] = False,
        external_ref: Annotated[str | None, Form(max_length=200)] = None,
        staging: bool = False,
    ) -> DocumentOut:
        """Save a source document: validated and language-detected before any translation.
        Identical bytes return the owner's existing document unless ``new_document``."""
        view, created = ctx.jobs.create_document(
            user.principal.user_id,
            file.filename or "document",
            file.file,
            new_document=new_document,
            external_ref=external_ref,
            staging=staging,
        )
        if not created:
            response.status_code = 200
        return DocumentOut.of(view)

    @router.get("/documents", tags=["documents"], responses=errors)
    def list_documents(  # pyright: ignore[reportUnusedFunction]
        user: User, cursor: Cursor = None, limit: Limit = 50, q: Search = None
    ) -> DocumentPage:
        page = ctx.jobs.list_documents(user.principal.user_id, cursor, limit, q)
        return DocumentPage(
            items=[DocumentOut.of(d) for d in page.items], next_cursor=page.next_cursor
        )

    @router.get("/documents/{document_id}", tags=["documents"], responses=errors)
    def get_document(document_id: str, user: User) -> DocumentOut:  # pyright: ignore[reportUnusedFunction]
        return DocumentOut.of(ctx.jobs.get_document(user.principal.user_id, document_id))

    @router.delete(
        "/documents/{document_id}", tags=["documents"], status_code=204, responses=errors
    )
    def delete_document(document_id: str, user: User) -> Response:  # pyright: ignore[reportUnusedFunction]
        """Delete the source and all its translations; job downloads of it stop too."""
        ctx.jobs.delete_document(user.principal.user_id, document_id)
        return Response(status_code=204)

    @router.get(
        "/documents/{document_id}/original",
        tags=["documents"],
        response_class=FileResponse,
        responses=errors,
    )
    def document_original(document_id: str, user: User) -> FileResponse:  # pyright: ignore[reportUnusedFunction]
        return _stream(ctx.jobs.document_original(user.principal.user_id, document_id))

    @router.post(
        "/documents/{document_id}/translations",
        tags=["documents"],
        status_code=202,
        response_model=JobOut | ItemOut,
        responses=submit_errors,
    )
    def translate_document(  # pyright: ignore[reportUnusedFunction]
        document_id: str, body: TranslateIn, user: User
    ) -> JSONResponse:
        """Translate a saved document: reuses its compatible current translation unless
        ``force_retranslate``; one unfinished job per target language (409 otherwise)."""
        result = ctx.jobs.translate_document(
            user.principal.user_id,
            document_id,
            _options(body),
            submission_id=str(body.submission_id) if body.submission_id else None,
            batch_id=body.batch_id,
            client_item_id=str(body.client_item_id) if body.client_item_id else None,
        )
        if result.item is not None:
            return _submitted(result, ItemOut.of(result.item))
        if result.job is None:  # pragma: no cover
            raise RuntimeError("submission without a job")
        return _submitted(result, JobOut.of(result.job))

    @router.get("/documents/{document_id}/translations", tags=["documents"], responses=errors)
    def list_translations(document_id: str, user: User) -> DocumentOut:  # pyright: ignore[reportUnusedFunction]
        return DocumentOut.of(ctx.jobs.get_document(user.principal.user_id, document_id))

    @router.delete(
        "/documents/{document_id}/translations/{translation_id}",
        tags=["documents"],
        status_code=204,
        responses=errors,
    )
    def delete_translation(  # pyright: ignore[reportUnusedFunction]
        document_id: str, translation_id: str, user: User
    ) -> Response:
        ctx.jobs.delete_translation(user.principal.user_id, document_id, translation_id)
        return Response(status_code=204)

    @router.get(
        "/documents/{document_id}/translations/{translation_id}/file",
        tags=["documents"],
        response_class=FileResponse,
        responses=errors,
    )
    def translation_file(  # pyright: ignore[reportUnusedFunction]
        document_id: str, translation_id: str, user: User
    ) -> FileResponse:
        return _stream(
            ctx.jobs.translation_file(user.principal.user_id, document_id, translation_id, "output")
        )

    @router.get(
        "/documents/{document_id}/translations/{translation_id}/fit-report",
        tags=["documents"],
        response_class=FileResponse,
        responses=errors,
    )
    def translation_report(  # pyright: ignore[reportUnusedFunction]
        document_id: str, translation_id: str, user: User
    ) -> FileResponse:
        return _stream(
            ctx.jobs.translation_file(user.principal.user_id, document_id, translation_id, "report")
        )

    @router.get("/history", tags=["history"], responses=errors)
    def history(user: User, cursor: Cursor = None, limit: Limit = 50) -> dict[str, Any]:  # pyright: ignore[reportUnusedFunction]
        return ctx.jobs.list_history(user.principal.user_id, cursor, limit)

    @router.get("/history/{identifier}/file", tags=["history"], responses=errors)
    def history_file(identifier: str, user: User) -> FileResponse:  # pyright: ignore[reportUnusedFunction]
        return _stream(ctx.jobs.history_file(user.principal.user_id, identifier))

    @router.delete("/history/{identifier}", tags=["history"], responses=errors, status_code=204)
    def delete_history(identifier: str, user: User) -> Response:  # pyright: ignore[reportUnusedFunction]
        ctx.jobs.delete_history(user.principal.user_id, identifier)
        return Response(status_code=204)

    @router.post("/batches", tags=["batches"], status_code=201, responses=errors)
    def create_batch(body: BatchCreate, user: User, response: Response) -> BatchOut:  # pyright: ignore[reportUnusedFunction]
        view, created = ctx.jobs.create_batch(
            user.principal.user_id, str(body.idempotency_key), body.label
        )
        if not created:
            response.status_code = 200
        return BatchOut.of(view)

    @router.get("/batches", tags=["batches"], responses=errors)
    def list_batches(user: User, cursor: Cursor = None, limit: Limit = 50) -> BatchPage:  # pyright: ignore[reportUnusedFunction]
        page = ctx.jobs.list_batches(user.principal.user_id, cursor, limit)
        return BatchPage(items=[BatchOut.of(b) for b in page.items], next_cursor=page.next_cursor)

    @router.get("/batches/{batch_id}", tags=["batches"], responses=errors)
    def get_batch(batch_id: str, user: User) -> BatchOut:  # pyright: ignore[reportUnusedFunction]
        return BatchOut.of(ctx.jobs.get_batch(user.principal.user_id, batch_id))

    @router.post(
        "/batches/{batch_id}/items",
        tags=["batches"],
        status_code=202,
        response_model=ItemOut,
        responses=submit_errors,
        dependencies=[Depends(upload_limit)],
    )
    def add_item(  # pyright: ignore[reportUnusedFunction]
        batch_id: str,
        user: User,
        file: Annotated[UploadFile, File()],
        options: Annotated[str, Form(description="SubmitOptionsIn as JSON")],
        client_item_id: Annotated[uuid.UUID, Form()],
    ) -> JSONResponse:
        """Upload one file into the batch (saved documents to reuse, or temporary)."""
        result = ctx.jobs.submit(
            user.principal.user_id,
            file.filename or "document",
            file.file,
            _parse_options(options),
            batch_id=batch_id,
            client_item_id=str(client_item_id),
        )
        if result.item is None:  # pragma: no cover
            raise RuntimeError("batch submission without an item")
        return _submitted(result, ItemOut.of(result.item))

    @router.get("/batches/{batch_id}/items", tags=["batches"], responses=errors)
    def list_items(  # pyright: ignore[reportUnusedFunction]
        batch_id: str,
        user: User,
        cursor: Cursor = None,
        limit: Limit = 50,
        client_item_id: Annotated[uuid.UUID | None, Query()] = None,
    ) -> ItemPage:
        page = ctx.jobs.list_items(
            user.principal.user_id,
            batch_id,
            cursor,
            limit,
            str(client_item_id) if client_item_id else None,
        )
        return ItemPage(items=[ItemOut.of(i) for i in page.items], next_cursor=page.next_cursor)

    @router.post("/batches/{batch_id}/seal", tags=["batches"], responses=errors)
    def seal_batch(batch_id: str, user: User) -> BatchOut:  # pyright: ignore[reportUnusedFunction]
        return BatchOut.of(ctx.jobs.seal_batch(user.principal.user_id, batch_id))

    @router.post("/batches/{batch_id}/cancel", tags=["batches"], responses=errors)
    def cancel_batch(batch_id: str, user: User) -> BatchOut:  # pyright: ignore[reportUnusedFunction]
        return BatchOut.of(ctx.jobs.cancel_batch(user.principal.user_id, batch_id))

    # Jobs

    @router.post(
        "/jobs",
        tags=["jobs"],
        status_code=202,
        response_model=JobOut,
        responses=submit_errors,
        dependencies=[Depends(upload_limit)],
    )
    def submit_job(  # pyright: ignore[reportUnusedFunction]
        user: User,
        file: Annotated[UploadFile, File()],
        options: Annotated[str, Form(description="SubmitOptionsIn as JSON")],
        submission_id: Annotated[uuid.UUID, Form()],
    ) -> JSONResponse:
        result = ctx.jobs.submit(
            user.principal.user_id,
            file.filename or "document",
            file.file,
            _parse_options(options),
            submission_id=str(submission_id),
        )
        if result.job is None:  # pragma: no cover
            raise RuntimeError("submission without a job")
        return _submitted(result, JobOut.of(result.job))

    @router.get("/jobs", tags=["jobs"], responses=errors)
    def list_jobs(  # pyright: ignore[reportUnusedFunction]
        user: User,
        cursor: Cursor = None,
        limit: Limit = 50,
        status: Annotated[
            str | None, Query(pattern="^(queued|running|succeeded|failed|cancelled)$")
        ] = None,
        q: Search = None,
        active: bool = False,
    ) -> JobPage:
        """Owned jobs, newest first. ``active`` keeps unfinished jobs and finished ones the user
        has not dismissed; ``q`` searches file names."""
        page = ctx.jobs.list_jobs(
            user.principal.user_id, cursor, limit, status, query=q, active=active
        )
        return JobPage(items=[JobOut.of(j) for j in page.items], next_cursor=page.next_cursor)

    @router.get("/jobs/{job_id}", tags=["jobs"], responses=errors)
    def get_job(job_id: str, user: User) -> JobOut:  # pyright: ignore[reportUnusedFunction]
        return JobOut.of(ctx.jobs.get_job(user.principal.user_id, job_id))

    @router.post("/jobs/{job_id}/cancel", tags=["jobs"], responses=errors)
    def cancel_job(job_id: str, user: User) -> JobOut:  # pyright: ignore[reportUnusedFunction]
        return JobOut.of(ctx.jobs.cancel_job(user.principal.user_id, job_id))

    @router.post("/jobs/{job_id}/dismiss", tags=["jobs"], responses=errors)
    def dismiss_job(job_id: str, user: User) -> JobOut:  # pyright: ignore[reportUnusedFunction]
        return JobOut.of(ctx.jobs.set_dismissed(user.principal.user_id, job_id, True))

    @router.post("/jobs/{job_id}/restore", tags=["jobs"], responses=errors)
    def restore_job(job_id: str, user: User) -> JobOut:  # pyright: ignore[reportUnusedFunction]
        return JobOut.of(ctx.jobs.set_dismissed(user.principal.user_id, job_id, False))

    @router.get("/jobs/{job_id}/file", tags=["jobs"], response_class=FileResponse, responses=errors)
    def job_file(job_id: str, user: User) -> FileResponse:  # pyright: ignore[reportUnusedFunction]
        """The job's exact output until ``result_expires_at``."""
        return _stream(ctx.jobs.job_file(user.principal.user_id, job_id, "output"))

    @router.get(
        "/jobs/{job_id}/fit-report", tags=["jobs"], response_class=FileResponse, responses=errors
    )
    def job_report(job_id: str, user: User) -> FileResponse:  # pyright: ignore[reportUnusedFunction]
        return _stream(ctx.jobs.job_file(user.principal.user_id, job_id, "report"))

    return router
