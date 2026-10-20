"""Unit tests for modular database repository and mixins."""

import pytest
from src.database.repository import DatabaseRepository
from src.database.mixins import (
    SchemaMixin,
    StateMixin,
    RolesMixin,
    AuditMixin,
    ChatMixin,
    NotesMixin,
    EndpointsMixin,
)


class TestDatabaseRepositoryComposition:
    def test_repository_inherits_all_mixins(self):
        repo = DatabaseRepository("postgresql://localhost:5432/azuris")
        assert isinstance(repo, SchemaMixin)
        assert isinstance(repo, StateMixin)
        assert isinstance(repo, RolesMixin)
        assert isinstance(repo, AuditMixin)
        assert isinstance(repo, ChatMixin)
        assert isinstance(repo, NotesMixin)
        assert isinstance(repo, EndpointsMixin)

    def test_command_count_parsing(self):
        assert DatabaseRepository._command_count("UPDATE 4") == 4
        assert DatabaseRepository._command_count("DELETE 12") == 12
        assert DatabaseRepository._command_count("INSERT 0 1") == 1
        assert DatabaseRepository._command_count("INVALID") == 0
        assert DatabaseRepository._command_count("") == 0

    def test_expected_methods_present(self):
        repo = DatabaseRepository("postgresql://localhost:5432/azuris")
        # Roles
        assert hasattr(repo, "is_admin_user")
        assert hasattr(repo, "is_moderator_user")
        assert hasattr(repo, "is_premium_user")
        # Chat
        assert hasattr(repo, "log_message_db")
        assert hasattr(repo, "get_user_history_from_db")
        # Notes
        assert hasattr(repo, "add_user_note_db")
        assert hasattr(repo, "get_user_notes_db")
        # Endpoints
        assert hasattr(repo, "get_llm_endpoints")
        assert hasattr(repo, "upsert_llm_model_slots")
        # State
        assert hasattr(repo, "set_user_processing_state")
        assert hasattr(repo, "clear_user_processing_state")
