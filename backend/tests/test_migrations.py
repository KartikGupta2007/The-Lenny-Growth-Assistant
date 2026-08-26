"""Migration correctness.

Alembic is the source of truth for the schema, which is only true if it is
checked. The central test here compares the migrated database against the
models and fails on any difference: without it, a model edit without a
migration would pass every other test in the suite -- because the tests would
be running on a schema built by that same missing migration -- and then fail on
deployment.

The other tests assert the things a review cannot see by reading the migration:
that the cascades, the check constraints and the HNSW index actually exist in
PostgreSQL with the properties intended.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, create_engine, text

from app.constants import BACKEND_DIR
from app.db.base import Base
from app.db.models import EMBEDDING_DIMENSIONS

EXPECTED_TABLES = {
    "users",
    "sessions",
    "messages",
    "artifacts",
    "documents",
    "chunks",
}

# pg_constraint.confdeltype codes.
CASCADE = "c"
SET_NULL = "n"

EXPECTED_FOREIGN_KEYS = {
    "fk_sessions_user_id_users": CASCADE,
    "fk_messages_session_id_sessions": CASCADE,
    "fk_artifacts_session_id_sessions": CASCADE,
    # Deleting a message must not destroy a document the user has open.
    "fk_artifacts_message_id_messages": SET_NULL,
    "fk_chunks_document_id_documents": CASCADE,
}

EXPECTED_INDEXES = {
    "ix_sessions_user_id",
    "ix_sessions_user_id_updated_at",
    "ix_messages_session_id",
    "ix_messages_session_id_created_at",
    "ix_artifacts_session_id",
    "ix_artifacts_message_id",
    "ix_documents_content_hash",
    "ix_chunks_document_id",
    "ix_chunks_content_hash",
    "ix_chunks_embedding_hnsw",
}


@pytest.fixture
def connection(migrated_database: str) -> Iterator[Connection]:
    """A blocking connection to the migrated test database.

    Blocking rather than async: every query here reads PostgreSQL's catalogs,
    and Alembic's comparison API is synchronous.
    """
    engine = create_engine(migrated_database)
    try:
        with engine.connect() as conn:
            yield conn
    finally:
        engine.dispose()


def alembic_config() -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    return config


class TestSchemaMatchesModels:
    def test_no_drift_between_migrations_and_models(
        self, connection: Connection
    ) -> None:
        """The migrated schema and the models agree, exactly.

        A non-empty diff means someone changed a model without writing the
        migration for it. The diff itself is the error message.
        """

        def include_object(obj, name, type_, reflected, compare_to):  # type: ignore[no-untyped-def]
            return not (type_ == "table" and name == "alembic_version")

        context = MigrationContext.configure(
            connection,
            opts={
                "compare_type": True,
                "compare_server_default": True,
                "include_object": include_object,
            },
        )

        diff = compare_metadata(context, Base.metadata)

        assert diff == [], f"schema drift: {diff}"


class TestMigrationChain:
    def test_there_is_exactly_one_head(self) -> None:
        """Two heads mean a branched history that cannot be applied linearly."""
        heads = ScriptDirectory.from_config(alembic_config()).get_heads()

        assert len(heads) == 1, f"expected one head, found {heads}"

    def test_the_database_is_stamped_at_head(self, connection: Connection) -> None:
        heads = ScriptDirectory.from_config(alembic_config()).get_heads()

        stamped = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalars().all()

        assert list(stamped) == list(heads)


class TestTables:
    def test_every_expected_table_exists(self, connection: Connection) -> None:
        present = set(
            connection.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public'"
                )
            ).scalars()
        )

        assert EXPECTED_TABLES <= present, f"missing: {EXPECTED_TABLES - present}"

    def test_no_unexpected_tables(self, connection: Connection) -> None:
        """Catches a table left behind by an edited migration."""
        present = set(
            connection.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public'"
                )
            ).scalars()
        )

        assert present - EXPECTED_TABLES == {"alembic_version"}


class TestForeignKeyActions:
    def test_delete_actions_are_as_intended(self, connection: Connection) -> None:
        """A wrong ON DELETE is invisible until it deletes the wrong thing."""
        rows = connection.execute(
            text(
                "SELECT conname, confdeltype FROM pg_constraint "
                "WHERE contype = 'f' AND connamespace = 'public'::regnamespace"
            )
        ).all()
        actual = {name: action for name, action in rows}

        assert actual == EXPECTED_FOREIGN_KEYS


class TestIndexes:
    def test_every_expected_index_exists(self, connection: Connection) -> None:
        present = set(
            connection.execute(
                text("SELECT indexname FROM pg_indexes WHERE schemaname = 'public'")
            ).scalars()
        )

        assert EXPECTED_INDEXES <= present, f"missing: {EXPECTED_INDEXES - present}"

    def test_the_vector_index_is_hnsw_over_cosine_distance(
        self, connection: Connection
    ) -> None:
        """An index built for the wrong operator is never used by the planner.

        Cosine, because RETRIEVAL_MAX_DISTANCE is a cosine distance. HNSW,
        because IVFFlat derives its lists from the rows present when the index
        is built and the table is empty at migration time.
        """
        definition = connection.execute(
            text("SELECT indexdef FROM pg_indexes WHERE indexname = :name"),
            {"name": "ix_chunks_embedding_hnsw"},
        ).scalar_one()

        assert "USING hnsw" in definition
        assert "vector_cosine_ops" in definition


class TestVectorColumn:
    def test_pgvector_extension_is_installed(self, connection: Connection) -> None:
        version = connection.execute(
            text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
        ).scalar_one_or_none()

        assert version is not None, "the migration must create the vector extension"

    def test_column_width_comes_from_configuration(
        self, connection: Connection
    ) -> None:
        """The migration sizes the column from settings, not from a literal."""
        declared = connection.execute(
            text(
                "SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
                "WHERE attrelid = 'chunks'::regclass AND attname = 'embedding'"
            )
        ).scalar_one()

        assert declared == f"vector({EMBEDDING_DIMENSIONS})"


class TestCheckConstraints:
    def test_role_and_type_constraints_exist(self, connection: Connection) -> None:
        names = set(
            connection.execute(
                text(
                    "SELECT conname FROM pg_constraint "
                    "WHERE contype = 'c' AND connamespace = 'public'::regnamespace"
                )
            ).scalars()
        )

        assert "ck_messages_message_role" in names
        assert "ck_artifacts_artifact_type" in names
        assert "ck_chunks_chunk_index_non_negative" in names

    def test_timestamps_are_timezone_aware(self, connection: Connection) -> None:
        """A naive timestamp column silently loses the offset on write."""
        naive = connection.execute(
            text(
                "SELECT table_name, column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' "
                "AND data_type = 'timestamp without time zone'"
            )
        ).all()

        assert naive == [], f"timezone-naive timestamp columns: {naive}"
