"""UUID hardening tests.

Weryfikuje że konwersje str → uuid.UUID są spójne w całym stosie:
- to_uuid() helper
- audit_service (actor_user_id)
- payment_service (imported_by, created_by)
- contractor_service (ContractorOverrideORM.created_by)
"""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest

from app.core.utils import to_uuid


# ---------------------------------------------------------------------------
# to_uuid() helper
# ---------------------------------------------------------------------------


class TestToUuid:
    def test_none_returns_none(self):
        assert to_uuid(None) is None

    def test_uuid_object_identity(self):
        u = uuid.uuid4()
        assert to_uuid(u) is u

    def test_str_valid_uuid(self):
        u = uuid.uuid4()
        result = to_uuid(str(u))
        assert result == u
        assert isinstance(result, UUID)

    def test_str_invalid_raises(self):
        with pytest.raises(ValueError):
            to_uuid("not-a-uuid")

    def test_does_not_raise_on_cast_to_str(self):
        """After to_uuid(), calling .hex must not raise AttributeError."""
        u = to_uuid(str(uuid.uuid4()))
        assert isinstance(u.hex, str)  # SQLAlchemy bind-processor requires .hex


# ---------------------------------------------------------------------------
# audit_service — actor_user_id conversion
# ---------------------------------------------------------------------------


class TestAuditServiceUuid:
    """Verifies that AuditService.record() converts str user_id to uuid.UUID."""

    def _make_service(self):
        from app.services.audit_service import AuditService
        from app.persistence.repositories.audit_repository import AuditRepository

        session = MagicMock()
        repo = MagicMock(spec=AuditRepository)
        repo.add = MagicMock(side_effect=lambda x: x)
        return AuditService(session=session, audit_repository=repo), repo

    def test_str_user_id_stored_as_uuid(self):
        svc, repo = self._make_service()
        user_id_str = str(uuid.uuid4())
        svc.record(
            actor_user_id=user_id_str,
            actor_role="administrator",
            event_type="test.event",
            entity_type="invoice",
            entity_id="e1",
        )
        audit_log = repo.add.call_args[0][0]
        assert isinstance(audit_log.actor_user_id, UUID), (
            f"Expected uuid.UUID, got {type(audit_log.actor_user_id)}"
        )
        assert audit_log.actor_user_id == UUID(user_id_str)

    def test_uuid_object_passes_unchanged(self):
        svc, repo = self._make_service()
        user_uuid = uuid.uuid4()
        svc.record(
            actor_user_id=user_uuid,
            actor_role="administrator",
            event_type="test.event",
            entity_type="invoice",
            entity_id="e1",
        )
        audit_log = repo.add.call_args[0][0]
        assert audit_log.actor_user_id == user_uuid

    def test_none_user_id_stored_as_none(self):
        svc, repo = self._make_service()
        svc.record(
            actor_user_id=None,
            actor_role=None,
            event_type="system.event",
            entity_type="system",
            entity_id="s1",
        )
        audit_log = repo.add.call_args[0][0]
        assert audit_log.actor_user_id is None


# ---------------------------------------------------------------------------
# payment_service — imported_by and created_by (PaymentAllocationORM)
# ---------------------------------------------------------------------------


class TestPaymentServiceUuid:
    """Verifies that PaymentService stores uuid.UUID objects, not raw strings."""

    def _make_service(self):
        from app.services.payment_service import PaymentService
        from app.core.security import AuthenticatedUser

        actor = AuthenticatedUser(
            user_id=str(uuid.uuid4()),
            username="testuser",
            role="administrator",
        )

        tx_repo = MagicMock()
        alloc_repo = MagicMock()
        inv_repo = MagicMock()
        audit = MagicMock()
        session = MagicMock()

        svc = PaymentService(
            session=session,
            bank_transaction_repository=tx_repo,
            allocation_repository=alloc_repo,
            invoice_repository=inv_repo,
            audit_service=audit,
        )
        return svc, actor, tx_repo, alloc_repo, inv_repo

    def test_import_csv_imported_by_is_uuid(self):
        from app.persistence.models.bank_transaction import BankTransactionORM

        svc, actor, tx_repo, alloc_repo, inv_repo = self._make_service()

        # Patch _run_matching_for_orm to avoid DB calls
        svc._run_matching_for_orm = MagicMock(return_value=None)
        tx_repo.get_by_external_id = MagicMock(return_value=None)
        tx_repo.add = MagicMock(side_effect=lambda x: x)

        svc.import_csv(
            "transaction_date,amount,currency,title\n2026-04-01,1000.00,PLN,Test przelew\n",
            source_file="test.csv",
            actor=actor,
        )

        added = tx_repo.add.call_args[0][0]
        assert isinstance(added.imported_by, UUID), (
            f"imported_by should be uuid.UUID, got {type(added.imported_by)}"
        )
        assert added.imported_by == UUID(actor.user_id)

    def test_do_allocate_created_by_is_uuid(self):
        from decimal import Decimal
        from app.persistence.models.bank_transaction import BankTransactionORM
        from app.persistence.models.payment_allocation import PaymentAllocationORM
        from app.domain.enums import PaymentMatchMethod

        svc, actor, tx_repo, alloc_repo, inv_repo = self._make_service()

        tx_orm = MagicMock(spec=BankTransactionORM)
        tx_orm.id = uuid.uuid4()
        tx_orm.amount = Decimal("1000.00")

        inv_orm = MagicMock()
        inv_orm.totals_json = {"total_gross": "1000.00"}

        alloc_repo.add = MagicMock(side_effect=lambda x: x)
        alloc_repo.sum_allocated_for_transaction = MagicMock(return_value=Decimal("1000.00"))
        alloc_repo.sum_allocated_for_invoice = MagicMock(return_value=Decimal("1000.00"))
        tx_repo.update_match_status = MagicMock()
        inv_repo.get_orm_by_id = MagicMock(return_value=inv_orm)
        inv_repo.update = MagicMock()

        invoice_id = uuid.uuid4()
        svc._do_allocate(
            tx_orm=tx_orm,
            invoice_id=invoice_id,
            amount=Decimal("1000.00"),
            method=PaymentMatchMethod.MANUAL,
            score=None,
            reasons=[],
            actor=actor,
        )

        alloc_added = alloc_repo.add.call_args[0][0]
        assert isinstance(alloc_added.created_by, UUID), (
            f"created_by should be uuid.UUID, got {type(alloc_added.created_by)}"
        )
        assert alloc_added.created_by == UUID(actor.user_id)


# ---------------------------------------------------------------------------
# contractor_service — ContractorOverrideORM.created_by
# ---------------------------------------------------------------------------


class TestContractorServiceUuid:
    def test_update_override_created_by_is_uuid(self):
        from app.services.contractor_service import ContractorService
        from app.core.security import AuthenticatedUser
        from app.persistence.models.contractor_override import ContractorOverrideORM

        actor = AuthenticatedUser(
            user_id=str(uuid.uuid4()),
            username="testuser",
            role="administrator",
        )

        session = MagicMock()
        contractor_repo = MagicMock()
        override_repo = MagicMock()
        audit_svc = MagicMock()

        contractor_id = uuid.uuid4()
        contractor_repo.get_by_id = MagicMock(return_value=MagicMock(id=contractor_id))
        override_repo.get_active_by_contractor_id = MagicMock(return_value=None)

        added_overrides = []

        def capture_add(orm):
            added_overrides.append(orm)

        override_repo.add = MagicMock(side_effect=capture_add)
        override_repo.save = MagicMock()
        session.flush = MagicMock()
        session.refresh = MagicMock()

        svc = ContractorService(
            session=session,
            contractor_repository=contractor_repo,
            contractor_override_repository=override_repo,
            audit_service=audit_svc,
            regon_client=MagicMock(),
            regon_mapper=MagicMock(),
        )

        svc.update_override(contractor_id, {"name": "Override Name"}, actor)

        assert len(added_overrides) == 1
        override_orm = added_overrides[0]
        assert isinstance(override_orm.created_by, UUID), (
            f"created_by should be uuid.UUID, got {type(override_orm.created_by)}"
        )
        assert override_orm.created_by == UUID(actor.user_id)
