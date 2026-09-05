"""Athena and output plumbing shared by the jobs that build the site's data.

Both jobs — the passenger-hours aggregation and the track-section map — read
from the same requester-pays dataset and write to the same site bucket, so the
Athena client and the local-dir-or-S3 output abstraction live here rather than
being written twice.

Nothing in here knows what a metric is. Keep it that way.
"""

from __future__ import annotations

import gzip
import json
import time
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlparse

import boto3
from botocore.config import Config


class Output:
    """Somewhere to put the built JSON — a local directory or an S3 prefix.

    The two behave identically from the caller's point of view, which is what
    lets the same code run from a laptop and from a Lambda.

    Names may contain slashes (``day/2026-09-04.json``). On S3 that is just a
    longer key; locally the parent directory is created on write.
    """

    def __init__(self, target: str) -> None:
        self._s3_bucket: str | None = None
        if target.startswith("s3://"):
            parsed = urlparse(target)
            self._s3_bucket = parsed.netloc
            self._prefix = parsed.path.strip("/")
            self._client = boto3.client("s3")
        else:
            self._dir = Path(target)
            self._dir.mkdir(parents=True, exist_ok=True)

    def __str__(self) -> str:
        return f"s3://{self._s3_bucket}/{self._prefix}" if self._s3_bucket else str(self._dir)

    def _key(self, name: str) -> str:
        return f"{self._prefix}/{name}" if self._prefix else name

    def read(self, name: str) -> str | None:
        """Existing contents, or None if it is not there yet."""
        raw = self.read_bytes(name)
        return raw.decode() if raw is not None else None

    def read_bytes(self, name: str) -> bytes | None:
        if self._s3_bucket:
            try:
                return self._client.get_object(
                    Bucket=self._s3_bucket, Key=self._key(name)
                )["Body"].read()
            except self._client.exceptions.NoSuchKey:
                return None
        path = self._dir / name
        return path.read_bytes() if path.exists() else None

    def write(self, name: str, text: str, cache_control: str = "max-age=300") -> None:
        self.write_bytes(name, text.encode(), "application/json", cache_control)

    def write_bytes(
        self,
        name: str,
        data: bytes,
        content_type: str = "application/octet-stream",
        cache_control: str = "max-age=300",
    ) -> None:
        if self._s3_bucket:
            self._client.put_object(
                Bucket=self._s3_bucket, Key=self._key(name), Body=data,
                ContentType=content_type, CacheControl=cache_control,
            )
        else:
            path = self._dir / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)

    def read_gzip_json(self, name: str) -> Any | None:
        """Read a gzipped JSON document, or None if it is not there yet."""
        raw = self.read_bytes(name)
        return json.loads(gzip.decompress(raw)) if raw is not None else None

    def write_gzip_json(self, name: str, value: Any) -> None:
        body = gzip.compress(json.dumps(value, separators=(",", ":")).encode())
        self.write_bytes(name, body, "application/json", "no-store")

    def delete(self, name: str) -> None:
        """Remove one file. Deleting something that is not there is not an error."""
        if self._s3_bucket:
            self._client.delete_object(Bucket=self._s3_bucket, Key=self._key(name))
        else:
            (self._dir / name).unlink(missing_ok=True)

    def list(self, prefix: str = "") -> list[str]:
        """Names under *prefix*, relative to this output's root."""
        if self._s3_bucket:
            root = self._key(prefix)
            paginator = self._client.get_paginator("list_objects_v2")
            names = []
            for page in paginator.paginate(Bucket=self._s3_bucket, Prefix=root):
                for obj in page.get("Contents", []):
                    key = obj["Key"]
                    names.append(key[len(self._prefix) + 1:] if self._prefix else key)
            return names
        base = self._dir / prefix
        if not base.is_dir():
            return []
        return sorted(
            str(p.relative_to(self._dir)) for p in base.rglob("*") if p.is_file()
        )


class Athena:
    """Minimal synchronous Athena client."""

    # A backfill makes hundreds of calls over several hours, and the default
    # of a few attempts is not enough to ride out a dropped connection or a
    # throttle. Losing the run to one blip is worse than waiting.
    RETRIES = Config(retries={"max_attempts": 10, "mode": "adaptive"})

    def __init__(self, database: str, workgroup: str, results: str, region: str) -> None:
        self._client = boto3.client("athena", region_name=region, config=self.RETRIES)
        self._database = database
        self._workgroup = workgroup
        self._results = results
        # What the last query cost, in bytes. Athena bills a 10 MB minimum
        # per query at $5/TB, so this is how you check a job stays cheap.
        self.bytes_scanned = 0

    def query(self, sql: str) -> list[dict[str, Any]]:
        request: dict[str, Any] = {
            "QueryString": sql,
            "QueryExecutionContext": {"Database": self._database},
            "WorkGroup": self._workgroup,
        }
        # A workgroup that enforces its own output location rejects an override.
        if self._results:
            request["ResultConfiguration"] = {"OutputLocation": self._results}

        execution_id = self._client.start_query_execution(**request)["QueryExecutionId"]

        while True:
            execution = self._client.get_query_execution(QueryExecutionId=execution_id)
            state = execution["QueryExecution"]["Status"]["State"]
            if state in ("SUCCEEDED", "FAILED", "CANCELLED"):
                break
            time.sleep(1)

        self.bytes_scanned = (
            execution["QueryExecution"].get("Statistics", {}).get("DataScannedInBytes", 0)
        )

        if state != "SUCCEEDED":
            reason = execution["QueryExecution"]["Status"].get("StateChangeReason", state)
            raise RuntimeError(f"Athena query {state}: {reason}")

        return list(self._rows(execution_id))

    def _rows(self, execution_id: str) -> Iterator[dict[str, Any]]:
        paginator = self._client.get_paginator("get_query_results")
        header: list[str] | None = None

        for page in paginator.paginate(QueryExecutionId=execution_id):
            rows = page["ResultSet"]["Rows"]
            if header is None:
                header = [c.get("VarCharValue", "") for c in rows[0]["Data"]]
                rows = rows[1:]
            for row in rows:
                values = [c.get("VarCharValue") for c in row["Data"]]
                yield dict(zip(header, values))
