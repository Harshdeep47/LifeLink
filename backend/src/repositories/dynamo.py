"""DynamoDB access primitives shared by every repository.

This is the only layer that knows about DynamoDB types, condition expressions and
pagination tokens. Services depend on repository interfaces, never on boto3
(ADR-0010), which is what lets the domain tests run with no AWS at all.

Local development points at DynamoDB Local via ``DYNAMODB_ENDPOINT`` (ADR-0011);
the same code runs against real DynamoDB in AWS.
"""
from __future__ import annotations

import os
from collections.abc import Iterable
from decimal import Decimal
from functools import lru_cache
from typing import Any

import boto3
from boto3.dynamodb.conditions import Key
from botocore.config import Config
from botocore.exceptions import ClientError

from domain.errors import ConcurrentModificationError, DuplicateError, LifeLinkError

TABLE_PREFIX = os.environ.get("LIFELINK_TABLE_PREFIX", "lifelink")


class Tables:
    ORGANIZATIONS = "organizations"
    FACILITIES = "facilities"
    INVENTORY = "inventory"
    ALERTS = "alerts"
    RESERVATIONS = "reservations"
    CAMPS = "camps"
    DONATIONS = "donations"
    EMERGENCY = "emergency"
    NOTIFICATIONS = "notifications"
    AUDIT = "audit"
    IDEMPOTENCY = "idempotency"
    OUTBOX = "outbox"

    @classmethod
    def all(cls) -> list[str]:
        return [
            cls.ORGANIZATIONS, cls.FACILITIES, cls.INVENTORY, cls.ALERTS,
            cls.RESERVATIONS,
            cls.CAMPS, cls.DONATIONS, cls.EMERGENCY, cls.NOTIFICATIONS,
            cls.AUDIT, cls.IDEMPOTENCY, cls.OUTBOX,
        ]


def table_name(logical: str) -> str:
    return f"{TABLE_PREFIX}-{logical}"


@lru_cache(maxsize=1)
def _resource():
    endpoint = os.environ.get("DYNAMODB_ENDPOINT")
    region = os.environ.get("AWS_REGION", "ap-southeast-2")
    kwargs: dict[str, Any] = {
        "region_name": region,
        # Retries matter at this account's concurrency ceiling (ADR-0014):
        # throttling is an expected condition, not an exceptional one.
        "config": Config(retries={"max_attempts": 5, "mode": "adaptive"}),
    }
    if endpoint:
        kwargs["endpoint_url"] = endpoint
        kwargs.setdefault("aws_access_key_id", os.environ.get("AWS_ACCESS_KEY_ID", "local"))
        kwargs.setdefault("aws_secret_access_key", os.environ.get("AWS_SECRET_ACCESS_KEY", "local"))
    return boto3.resource("dynamodb", **kwargs)


def get_table(logical: str):
    return _resource().Table(table_name(logical))


def reset_resource_cache() -> None:
    """Used by tests that swap the endpoint between cases."""
    _resource.cache_clear()


# --- (de)serialisation -------------------------------------------------------

def to_dynamo(value: Any) -> Any:
    """Convert Python values into DynamoDB-safe ones.

    Floats are rejected by DynamoDB, so they become Decimals. Empty strings are
    preserved (DynamoDB has allowed them since 2020) but None is dropped by the
    caller rather than stored as NULL where an attribute should be absent.
    """
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {k: to_dynamo(v) for k, v in value.items() if v is not None}
    if isinstance(value, (list, tuple)):
        return [to_dynamo(v) for v in value]
    if isinstance(value, set):
        return {to_dynamo(v) for v in value}
    return value


def from_dynamo(value: Any) -> Any:
    """Convert DynamoDB values back to plain Python.

    Decimals become int when integral, float otherwise -- so unit counts come
    back as ints and never as 5.0 in a JSON response.
    """
    if isinstance(value, Decimal):
        return int(value) if value % 1 == 0 else float(value)
    if isinstance(value, dict):
        return {k: from_dynamo(v) for k, v in value.items()}
    if isinstance(value, list):
        return [from_dynamo(v) for v in value]
    if isinstance(value, set):
        return {from_dynamo(v) for v in value}
    return value


def clean(item: dict) -> dict:
    """Drop None values so absent attributes are genuinely absent."""
    return {k: to_dynamo(v) for k, v in item.items() if v is not None}


def to_expression_values(values: dict) -> dict:
    """Serialize ExpressionAttributeValues, preserving None.

    Deliberately different from ``to_dynamo``, which drops None so that an
    optional attribute is simply absent from a stored item. That is wrong here:
    an update expression that references ``:reason`` must be given ``:reason``,
    and silently dropping it makes DynamoDB reject the entire request with
    ValidationException. A None becomes a NULL attribute instead.
    """
    serialized: dict[str, Any] = {}
    for key, value in values.items():
        if value is None:
            serialized[key] = None
        elif isinstance(value, float):
            serialized[key] = Decimal(str(value))
        elif isinstance(value, dict):
            serialized[key] = {k: to_dynamo(v) for k, v in value.items()}
        elif isinstance(value, (list, tuple)):
            serialized[key] = [to_dynamo(v) for v in value]
        else:
            serialized[key] = to_dynamo(value)
    return serialized


# --- error translation -------------------------------------------------------

def translate_client_error(exc: ClientError, *, context: str = "") -> LifeLinkError:
    code = exc.response.get("Error", {}).get("Code", "")
    if code == "ConditionalCheckFailedException":
        return ConcurrentModificationError(
            f"the record changed while this operation was in flight{': ' + context if context else ''}",
            details={"hint": "re-read the record and retry"},
        )
    if code == "TransactionCanceledException":
        reasons = exc.response.get("CancellationReasons", []) or []
        codes = [r.get("Code") for r in reasons]
        if "ConditionalCheckFailed" in codes:
            return ConcurrentModificationError(
                "a concurrent change prevented this transaction from completing",
                details={"reasons": codes},
            )
        if "TransactionConflict" in codes:
            return ConcurrentModificationError(
                "another transaction is modifying these records",
                details={"reasons": codes},
            )
        return LifeLinkError(f"transaction cancelled: {codes}")
    if code in ("ProvisionedThroughputExceededException", "ThrottlingException",
                "RequestLimitExceeded"):
        from domain.errors import RateLimitedError

        return RateLimitedError("the datastore is throttling requests; retry shortly")
    if code == "ResourceNotFoundException":
        from domain.errors import NotFoundError

        return NotFoundError(f"storage table not found{': ' + context if context else ''}")
    return LifeLinkError(f"datastore error ({code}){': ' + context if context else ''}")


class DynamoRepository:
    """Base class with the query/write helpers every repository needs."""

    logical_table: str = ""

    def __init__(self, table=None):
        self._table = table

    @property
    def table(self):
        if self._table is None:
            self._table = get_table(self.logical_table)
        return self._table

    # --- reads ---

    def get(self, pk: str, sk: str) -> dict | None:
        try:
            response = self.table.get_item(Key={"PK": pk, "SK": sk})
        except ClientError as exc:
            raise translate_client_error(exc, context=self.logical_table) from exc
        item = response.get("Item")
        return from_dynamo(item) if item else None

    def get_consistent(self, pk: str, sk: str) -> dict | None:
        """Strongly consistent read, for read-after-write decision points only."""
        try:
            response = self.table.get_item(Key={"PK": pk, "SK": sk}, ConsistentRead=True)
        except ClientError as exc:
            raise translate_client_error(exc, context=self.logical_table) from exc
        item = response.get("Item")
        return from_dynamo(item) if item else None

    def query(
        self,
        *,
        key_condition,
        index_name: str | None = None,
        limit: int | None = None,
        exclusive_start_key: dict | None = None,
        scan_forward: bool = True,
        filter_expression=None,
        projection: str | None = None,
    ) -> tuple[list[dict], dict | None]:
        kwargs: dict[str, Any] = {
            "KeyConditionExpression": key_condition,
            "ScanIndexForward": scan_forward,
        }
        if index_name:
            kwargs["IndexName"] = index_name
        if limit:
            kwargs["Limit"] = limit
        if exclusive_start_key:
            kwargs["ExclusiveStartKey"] = exclusive_start_key
        if filter_expression is not None:
            kwargs["FilterExpression"] = filter_expression
        if projection:
            kwargs["ProjectionExpression"] = projection
        try:
            response = self.table.query(**kwargs)
        except ClientError as exc:
            raise translate_client_error(exc, context=self.logical_table) from exc
        items = [from_dynamo(i) for i in response.get("Items", [])]
        return items, response.get("LastEvaluatedKey")

    def query_all(self, *, key_condition, index_name: str | None = None,
                  filter_expression=None, max_items: int = 1000) -> list[dict]:
        """Page through a query to completion, with a hard ceiling.

        The ceiling exists so a pathological partition cannot turn one request
        into an unbounded read -- which at this account's concurrency limit would
        be felt immediately.
        """
        collected: list[dict] = []
        start_key = None
        while True:
            items, start_key = self.query(
                key_condition=key_condition,
                index_name=index_name,
                exclusive_start_key=start_key,
                filter_expression=filter_expression,
            )
            collected.extend(items)
            if not start_key or len(collected) >= max_items:
                break
        return collected[:max_items]

    def query_partition(self, pk: str, *, sk_prefix: str | None = None, **kwargs):
        condition = Key("PK").eq(pk)
        if sk_prefix:
            condition = condition & Key("SK").begins_with(sk_prefix)
        return self.query(key_condition=condition, **kwargs)

    # --- writes ---

    def put(self, item: dict, *, condition=None, on_conflict: str = "duplicate") -> dict:
        """Write an item, optionally guarded by a condition.

        ``on_conflict`` says what a failed condition *means*, because the two
        cases need different errors and different client behaviour:

        * ``"duplicate"`` -- the condition was a uniqueness check
          (``attribute_not_exists``), so a failure means the record already
          exists. The caller should not retry.
        * ``"version"`` -- the condition was an optimistic-concurrency check, so
          a failure means someone else wrote first. The caller should re-read and
          retry, which is what the service layer does on
          ConcurrentModificationError.

        Returning DuplicateError for a version conflict would be actively
        harmful: the retry path would never trigger and the user would be told
        the record already exists.
        """
        kwargs: dict[str, Any] = {"Item": clean(item)}
        if condition is not None:
            kwargs["ConditionExpression"] = condition
        try:
            self.table.put_item(**kwargs)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code == "ConditionalCheckFailedException" and condition is not None:
                if on_conflict == "version":
                    raise ConcurrentModificationError(
                        "the record changed while this operation was in flight",
                        details={"table": self.logical_table, "hint": "re-read and retry"},
                    ) from exc
                raise DuplicateError(
                    "a record with this identity already exists",
                    details={"table": self.logical_table},
                ) from exc
            raise translate_client_error(exc, context=self.logical_table) from exc
        return item

    def update(
        self,
        *,
        pk: str,
        sk: str,
        update_expression: str,
        expression_values: dict,
        expression_names: dict | None = None,
        condition=None,
        return_values: str = "ALL_NEW",
    ) -> dict:
        kwargs: dict[str, Any] = {
            "Key": {"PK": pk, "SK": sk},
            "UpdateExpression": update_expression,
            # Must preserve None: see to_expression_values.
            "ExpressionAttributeValues": to_expression_values(expression_values),
            "ReturnValues": return_values,
        }
        if expression_names:
            kwargs["ExpressionAttributeNames"] = expression_names
        if condition is not None:
            kwargs["ConditionExpression"] = condition
        try:
            response = self.table.update_item(**kwargs)
        except ClientError as exc:
            raise translate_client_error(exc, context=self.logical_table) from exc
        return from_dynamo(response.get("Attributes", {}))

    def delete(self, pk: str, sk: str, *, condition=None) -> None:
        kwargs: dict[str, Any] = {"Key": {"PK": pk, "SK": sk}}
        if condition is not None:
            kwargs["ConditionExpression"] = condition
        try:
            self.table.delete_item(**kwargs)
        except ClientError as exc:
            raise translate_client_error(exc, context=self.logical_table) from exc

    def batch_put(self, items: Iterable[dict]) -> int:
        count = 0
        with self.table.batch_writer() as batch:
            for item in items:
                batch.put_item(Item=clean(item))
                count += 1
        return count


def transact_write(operations: list[dict]) -> None:
    """Execute a DynamoDB transaction, translating cancellation reasons.

    Used wherever an invariant spans items: outbox + domain write (ADR-0005),
    registration + capacity counter, donation + ledger entry.
    """
    client = _resource().meta.client
    try:
        client.transact_write_items(TransactItems=operations)
    except ClientError as exc:
        raise translate_client_error(exc, context="transaction") from exc
