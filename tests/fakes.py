"""In-memory fakes so the API suite runs without a live database.

``FakeSession`` implements the slice of the AsyncSession API the services use:
``execute`` of a ``select(Model)...`` (with WHERE, ORDER BY, LIMIT/OFFSET) and of
``select(func.count())``; ``scalar_one_or_none`` / ``scalar_one`` /
``scalars().all()``; ``add``; ``delete``; ``flush`` (emulating the unique-email
constraint); ``rollback``; ``commit``; and async context management. The WHERE
clause is evaluated by walking the SQLAlchemy expression tree and comparing
column attribute values on the stored model instances.

This is a MOCK of the database layer, clearly labelled. It does NOT verify real
PostgreSQL behaviour (real constraints, JSONB, UUID generation, atomic upserts,
cascade deletes); live migration and DB integration remain unverified.
"""

from __future__ import annotations

import operator
import uuid
from typing import Any

from app.db.models.assets import Asset
from app.db.models.claims import Claim, ClaimDocument
from app.db.models.engagement import Announcement, Notification
from app.db.models.family import FamilyMember
from app.db.models.files import StoredFile
from app.db.models.identity import (
    Invite,
    PasswordResetToken,
    User,
    UserProfile,
    UserSetting,
)
from app.db.models.kyc import KycDocument
from app.db.models.policies import Policy
from app.db.models.reference import MasterData
from app.db.models.support import SupportTicket, TicketMessage
from app.db.models.transactions import Transaction
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql.elements import (
    BinaryExpression,
    BooleanClauseList,
    Grouping,
    UnaryExpression,
)
from sqlalchemy.sql.operators import eq, ge, gt, le, lt, ne

_MODEL_TYPES = [
    User, UserProfile, UserSetting, Invite, PasswordResetToken,
    Policy, Asset, FamilyMember, Claim, ClaimDocument, Transaction,
    Notification, Announcement, SupportTicket, TicketMessage, MasterData,
    StoredFile, KycDocument,
]

_OP_MAP = {
    eq: operator.eq,
    ne: operator.ne,
    lt: operator.lt,
    le: operator.le,
    gt: operator.gt,
    ge: operator.ge,
}


def _coerce(actual: Any, expected: Any) -> tuple[Any, Any]:
    if isinstance(actual, uuid.UUID) or isinstance(expected, uuid.UUID):
        return (
            str(actual) if actual is not None else None,
            str(expected) if expected is not None else None,
        )
    return actual, expected


def _match(row: Any, clause: Any) -> bool:
    # Parenthesised group (e.g. an or_(...) nested in an outer AND): unwrap it.
    if isinstance(clause, Grouping):
        return _match(row, clause.element)
    # AND / OR boolean lists.
    if isinstance(clause, BooleanClauseList):
        op = clause.operator
        results = [_match(row, c) for c in clause.clauses]
        if op is operator.or_ or getattr(op, "__name__", "") == "or_":
            return any(results)
        return all(results)
    if isinstance(clause, BinaryExpression):
        left = clause.left
        col_name = getattr(left, "name", None)
        op = clause.operator
        op_name = getattr(op, "__name__", "")
        actual = getattr(row, col_name, None) if col_name else None
        right = clause.right

        # Right-hand side value: plain bind params expose `.value`; SQL boolean
        # constants (True_/False_) do not, so detect them structurally.
        right_type = type(right).__name__
        if right_type == "True_":
            right_value: Any = True
        elif right_type == "False_":
            right_value = False
        elif right_type == "Null":
            right_value = None
        else:
            right_value = getattr(right, "value", None)

        # IS / IS NOT (NULL or boolean)
        if op_name in ("is_", "is") or op is operator.is_:
            if right_value is None:
                return actual is None
            return bool(actual) == bool(right_value)
        if op_name in ("isnot", "is_not") or op is operator.is_not:
            if right_value is None:
                return actual is not None
            return bool(actual) != bool(right_value)
        # ILIKE (case-insensitive contains, '%term%')
        if op_name == "ilike_op" or "ilike" in op_name:
            pattern = str(right_value).strip("%").lower()
            return actual is not None and pattern in str(actual).lower()

        actual_cmp, expected_cmp = _coerce(actual, right_value)
        py_op = _OP_MAP.get(op, operator.eq)
        try:
            return bool(py_op(actual_cmp, expected_cmp))
        except TypeError:
            return False
    # Fallback: a bare boolean column expression (is_(True)/is_(False)) handled
    # above; anything else we do not understand -> match-all is unsafe, so fail.
    raise AssertionError(f"unsupported where clause: {clause!r}")


def _order_rows(rows: list[Any], statement: Any) -> list[Any]:
    clauses = list(getattr(statement, "_order_by_clauses", []) or [])
    for clause in reversed(clauses):
        descending = isinstance(clause, UnaryExpression) and (
            getattr(clause.modifier, "__name__", "") == "desc_op"
        )
        col = clause.element if isinstance(clause, UnaryExpression) else clause
        name = getattr(col, "name", None)
        if not name:
            continue
        rows = sorted(
            rows,
            key=lambda r: (getattr(r, name, None) is not None, getattr(r, name, None)),
            reverse=descending,
        )
    return rows


class _Result:
    def __init__(self, rows: list[Any], *, scalar: Any = None, is_scalar: bool = False) -> None:
        self._rows = rows
        self._scalar = scalar
        self._is_scalar = is_scalar

    def scalar_one_or_none(self) -> Any:
        if self._is_scalar:
            return self._scalar
        return self._rows[0] if self._rows else None

    def scalar_one(self) -> Any:
        if self._is_scalar:
            return self._scalar
        if len(self._rows) != 1:
            raise AssertionError("scalar_one expected exactly one row")
        return self._rows[0]

    def scalars(self) -> _Result:
        return self

    def all(self) -> list[Any]:
        return list(self._rows)


class FakeStore:
    """Holds model instances grouped by type."""

    def __init__(self) -> None:
        self.data: dict[type, list[Any]] = {m: [] for m in _MODEL_TYPES}

    def seed(self, *objs: Any) -> None:
        for obj in objs:
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()
            self.data.setdefault(type(obj), []).append(obj)


def _entity_of(statement: Any) -> Any:
    desc = statement.column_descriptions[0]
    return desc.get("entity")


class FakeSession:
    """Minimal async SQLAlchemy session stand-in over a FakeStore."""

    def __init__(self, store: FakeStore) -> None:
        self._store = store

    async def execute(self, statement: Any) -> _Result:
        entity = _entity_of(statement)
        is_count = entity is None  # select(func.count())

        if is_count:
            # Determine the table being counted from the FROM clause.
            froms = statement.get_final_froms()
            model = None
            for m in _MODEL_TYPES:
                if m.__table__ in froms:
                    model = m
                    break
            rows = list(self._store.data.get(model, [])) if model else []
            where = statement.whereclause
            if where is not None:
                rows = [r for r in rows if _match(r, where)]
            return _Result([], scalar=len(rows), is_scalar=True)

        rows = list(self._store.data.get(entity, []))
        where = statement.whereclause
        if where is not None:
            rows = [r for r in rows if _match(r, where)]
        rows = _order_rows(rows, statement)
        offset = statement._offset
        limit = statement._limit
        if offset is not None:
            rows = rows[offset:]
        if limit is not None:
            rows = rows[:limit]
        return _Result(rows)

    def add(self, obj: Any) -> None:
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        self._store.data.setdefault(type(obj), []).append(obj)

    async def delete(self, obj: Any) -> None:
        bucket = self._store.data.get(type(obj), [])
        self._store.data[type(obj)] = [o for o in bucket if o is not obj]

    async def flush(self) -> None:
        # Emulate the unique-email constraint firing at flush time.
        emails = [u.email for u in self._store.data[User]]
        dupes = {e for e in emails if emails.count(e) > 1}
        if dupes:
            raise IntegrityError("duplicate email", params=None, orig=Exception())

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None

    async def __aenter__(self) -> FakeSession:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None
