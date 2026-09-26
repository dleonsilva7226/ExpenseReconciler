"""D2 model sanity tests (priority 6 of the Q1 ticket).

These only introspect SQLAlchemy's declared table metadata -- no
engine/DB connection is created or needed -- confirming the two things
A1's spec (and its 2026-09-20 amendments) require and that would be
easy to silently regress:

1. `plaid_access_token_encrypted` is a `bytea`/`LargeBinary` column,
   not plaintext text -- it's meant to hold a `pgcrypto`-encrypted
   value, never a plain string.
2. `CreditAccount` identity is the *pair* `(plaid_item_id,
   plaid_account_id)` -- a composite unique constraint -- not a
   single-column uniqueness on `plaid_item_id` alone. The single-column
   version is exactly the bug A1's "Item vs. account identity"
   amendment fixed (one Plaid Item can cover multiple accounts); a
   regression back to single-column uniqueness would silently drop
   every account past the first one linked under an Item.
"""

from __future__ import annotations

from sqlalchemy import LargeBinary, UniqueConstraint

from app.domains.finance.models import CreditAccount, FinancialTransaction


def test_plaid_access_token_column_is_binary_not_plaintext():
    column = CreditAccount.__table__.columns["plaid_access_token_encrypted"]
    assert isinstance(column.type, LargeBinary)


def test_plaid_access_token_column_is_nullable():
    # An account can be linked in steps / re-linked; A1 marks this
    # nullable rather than required at insert time.
    column = CreditAccount.__table__.columns["plaid_access_token_encrypted"]
    assert column.nullable is True


def test_credit_account_identity_is_composite_item_and_account_not_item_alone():
    column = CreditAccount.__table__.columns["plaid_item_id"]
    # The pre-amendment bug was exactly `plaid_item_id` carrying
    # single-column `unique=True` -- guard against a regression back
    # to that, which would silently reject/drop every account past the
    # first one under a multi-account Item.
    assert column.unique is not True

    unique_constraints = [
        c for c in CreditAccount.__table__.constraints if isinstance(c, UniqueConstraint)
    ]
    assert len(unique_constraints) == 1, (
        "expected exactly one composite UniqueConstraint on CreditAccount, "
        f"found {len(unique_constraints)}"
    )
    constrained_columns = {col.name for col in unique_constraints[0].columns}
    assert constrained_columns == {"plaid_item_id", "plaid_account_id"}


def test_credit_account_has_plaid_account_id_column():
    assert "plaid_account_id" in CreditAccount.__table__.columns


def test_financial_transaction_provider_transaction_id_is_globally_unique():
    # This is the idempotency key `service.ingest_transactions` upserts
    # on (A1's "Idempotency" section) -- it must stay unique so a
    # duplicate ingest can be detected as an update, not a second row.
    column = FinancialTransaction.__table__.columns["provider_transaction_id"]
    assert column.unique is True
    assert column.nullable is False


def test_financial_transaction_account_id_foreign_key_targets_credit_accounts():
    column = FinancialTransaction.__table__.columns["account_id"]
    assert len(column.foreign_keys) == 1
    fk = next(iter(column.foreign_keys))
    assert fk.target_fullname == "credit_accounts.id"


def test_models_share_uuid_primary_key_and_timestamp_mixins():
    for model in (CreditAccount, FinancialTransaction):
        assert "id" in model.__table__.columns
        assert "created_at" in model.__table__.columns
        assert "updated_at" in model.__table__.columns
