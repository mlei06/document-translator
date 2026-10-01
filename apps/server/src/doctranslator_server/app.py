"""Composition root: builds the database, storage, engine catalog, services and the FastAPI app."""

from dataclasses import dataclass
from datetime import timedelta
from importlib.metadata import PackageNotFoundError, version
from typing import cast

from fastapi import FastAPI

from doctranslator_server.api import ApiContext, install
from doctranslator_server.auth import Authenticator
from doctranslator_server.db import Database
from doctranslator_server.jobs.engines import EngineCatalog, EngineIdentities, load_font_manifest
from doctranslator_server.jobs.queue import Queue
from doctranslator_server.jobs.service import JobService
from doctranslator_server.jobs.storage import BlobStore
from doctranslator_server.settings import ServerSettings

__all__ = [
    "Admin",
    "Services",
    "build_services",
    "create_app",
    "migrate",
    "open_admin",
    "openapi_document",
    "package_version",
]


def package_version(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:  # pragma: no cover - bare source tree
        return "0+unknown"


@dataclass
class Services:
    settings: ServerSettings
    db: Database
    store: BlobStore
    catalog: EngineIdentities
    jobs: JobService
    auth: Authenticator

    def queue(self) -> Queue:
        return Queue(
            self.db,
            lease=timedelta(seconds=self.settings.lease_s),
            retry_delays=self.settings.retry_delays_s,
            temporary_retention=timedelta(hours=self.settings.temporary_retention_hours),
            superseded_retention=timedelta(days=self.settings.superseded_retention_days),
        )

    def close(self) -> None:
        self.catalog.close()
        self.db.dispose()


def open_database(settings: ServerSettings) -> Database:
    return Database(settings.database)


def migrate(settings: ServerSettings) -> str | None:
    """Bring the database to the current schema; returns the revision."""
    db = open_database(settings)
    try:
        db.migrate()
        return db.current_revision()
    finally:
        db.dispose()


@dataclass
class Admin:
    """Database and storage for administrative commands (no engines or fonts are loaded)."""

    settings: ServerSettings
    db: Database
    store: BlobStore

    def close(self) -> None:
        self.db.dispose()


def open_admin(settings: ServerSettings) -> Admin:
    db = open_database(settings)
    try:
        db.require_current()
    except BaseException:
        db.dispose()
        raise
    store = BlobStore(
        settings.data_dir,
        db,
        pin_ttl=timedelta(hours=settings.staging_retention_hours),
        settings=settings,
    )
    return Admin(settings, db, store)


def build_services(
    settings: ServerSettings, *, catalog: EngineIdentities | None = None
) -> Services:
    """Everything a web or worker process needs; refuses an unmigrated database."""
    admin = open_admin(settings)
    db, store = admin.db, admin.store
    if catalog is None:
        catalog = EngineCatalog(settings, load_font_manifest(settings))
    return Services(
        settings=settings,
        db=db,
        store=store,
        catalog=catalog,
        jobs=JobService(settings, db, store, catalog),
        auth=Authenticator(db),
    )


def create_app(services: Services) -> FastAPI:
    app = FastAPI(
        title="Document Translator",
        version=package_version("doctranslator-server"),
        openapi_url="/v1/openapi.json",
        docs_url="/v1/docs",
        redoc_url=None,
    )
    install(
        app,
        ApiContext(
            jobs=services.jobs,
            auth=services.auth,
            service_version=package_version("doctranslator-server"),
            core_version=package_version("doctranslator-core"),
            max_upload_bytes=services.settings.max_upload_bytes,
            web_dir=services.settings.web_dir,
            registration_enabled=services.settings.registration_enabled,
        ),
    )
    return app


def openapi_document() -> dict[str, object]:
    """The ``/v1`` OpenAPI document, built without a database or engines (for client generation).

    Routes only reach the services when a request is handled, so a placeholder context suffices.
    """
    app = FastAPI(
        title="Document Translator",
        version=package_version("doctranslator-server"),
        openapi_url="/v1/openapi.json",
    )
    placeholder = ApiContext(
        jobs=cast(JobService, None),
        auth=cast(Authenticator, None),
        service_version=package_version("doctranslator-server"),
        core_version=package_version("doctranslator-core"),
        max_upload_bytes=ServerSettings.model_fields["max_upload_bytes"].default,
    )
    install(app, placeholder)
    return app.openapi()
