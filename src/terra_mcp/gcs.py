"""Read-only Google Cloud Storage access with two interchangeable backends.

The default backend is the ``google-cloud-storage`` client, which speaks the GCS
**JSON** API and only ever connects to ``storage.googleapis.com``.

Claude Science runs local MCP servers inside a sandbox whose proxy enforces a
per-connector domain allowlist, and ``storage.googleapis.com`` is permanently
blocked there ("Use the bucket's own address, like
my-bucket.storage.googleapis.com"). Those per-bucket virtual-hosted names serve
the GCS **XML** API, not the JSON API, so the stock client cannot be pointed at
them. The ``xml`` backend below talks to ``{bucket}.storage.googleapis.com``
with plain ``requests`` and covers every read operation this server needs.

Backend selection (``--gcs-backend``):

* ``json`` — always use ``google-cloud-storage``.
* ``xml``  — always use the XML API.
* ``auto`` (default) — try JSON once; if the host turns out to be unreachable
  (proxy refusal, DNS failure), switch to XML and remember that for the life of
  the process.

Both backends return the same dict shapes and raise the same
``google.cloud.exceptions`` NotFound / Forbidden, so callers do not branch.
"""

from __future__ import annotations

import base64
import binascii
import email.utils
import logging
import os
import urllib.parse
import xml.etree.ElementTree as ET
from typing import Any, Literal

import google.auth
import google.auth.transport.requests
import requests
from google.cloud import storage
from google.cloud.exceptions import Forbidden, NotFound

logger = logging.getLogger(__name__)

Backend = Literal["auto", "json", "xml"]
BACKENDS = ("auto", "json", "xml")

# The GCS XML API is S3-compatible and still uses the historical S3 namespace.
_XML_NS = {"s3": "http://doc.s3.amazonaws.com/2006-03-01"}
_XML_MAX_KEYS = 1000
_READ_SCOPE = "https://www.googleapis.com/auth/devstorage.read_only"
# (connect, read) seconds. Reads are generous: a download streams through here.
_TIMEOUT = (10, 300)
_CHUNK = 1 << 20

# storage.Client() insists on a project even for reads that never use one. With
# user ADC and no readable gcloud config (the sandbox sets HOME elsewhere) there
# is nothing to infer, so a placeholder goes in. See _json_client().
_PLACEHOLDER_PROJECT = "terra-mcp-no-project"

_requested_backend: str = "auto"
_active_backend: str | None = None
_session: requests.Session | None = None
_credentials: Any = None


# ===== Backend selection =====


def set_backend(name: str) -> None:
    """Select the backend, resetting any cached auto-detection result."""
    global _requested_backend, _active_backend
    if name not in BACKENDS:
        raise ValueError(f"Unknown GCS backend {name!r}; expected one of {BACKENDS}")
    _requested_backend = name
    _active_backend = None if name == "auto" else name


def active_backend() -> str:
    """Backend currently in use ("auto" until the first operation resolves it)."""
    return _active_backend or _requested_backend


# Markers that mean "this host is unreachable from here", as opposed to "GCS
# said no". Only these trigger the auto fallback; a 403 from GCS itself is a
# real permission answer and must not silently switch backends.
_BLOCKED_TYPES = frozenset(
    {
        "ProxyError",
        "ConnectionError",
        "ConnectTimeout",
        "NewConnectionError",
        "MaxRetryError",
        "gaierror",
        "TransportError",
    }
)
_BLOCKED_MARKERS = (
    "not on the allowlist",
    "tunnel connection failed",
    "failed to establish a new connection",
    "name or service not known",
    "nodename nor servname",
    "temporary failure in name resolution",
)


def _looks_unreachable(exc: BaseException) -> bool:
    """True if exc (or anything it was raised from) is a connection-level failure."""
    seen: BaseException | None = exc
    for _ in range(10):
        if seen is None:
            break
        if type(seen).__name__ in _BLOCKED_TYPES:
            return True
        text = str(seen).lower()
        if any(marker in text for marker in _BLOCKED_MARKERS):
            return True
        seen = seen.__cause__ or seen.__context__
    return False


def _call(op: str, *args: Any, **kwargs: Any) -> Any:
    global _active_backend
    if _active_backend is not None:
        return _IMPL[_active_backend][op](*args, **kwargs)

    # auto, not yet resolved: prefer JSON, fall back once on a dead host.
    try:
        result = _IMPL["json"][op](*args, **kwargs)
    except (NotFound, Forbidden):
        _active_backend = "json"  # GCS answered, so the host is reachable
        raise
    except Exception as exc:
        if not _looks_unreachable(exc):
            raise
        logger.warning(
            "GCS JSON API (storage.googleapis.com) is unreachable: %s: %s. "
            "Falling back to the XML API on per-bucket hostnames.",
            type(exc).__name__,
            exc,
        )
        _active_backend = "xml"
        return _IMPL["xml"][op](*args, **kwargs)
    _active_backend = "json"
    return result


# ===== Public interface =====


def list_objects(
    bucket: str, prefix: str, max_results: int, delimiter: str | None
) -> dict[str, Any]:
    """List up to max_results objects.

    Returns {"objects": [...], "prefixes": [...], "truncated": bool}. Each
    object has name, size, content_type, updated, md5_hash. When delimiter is
    "/" the listing is one level deep and "prefixes" holds the subdirectories.
    """
    return _call("list_objects", bucket, prefix, max_results, delimiter)


def stat_object(bucket: str, key: str) -> dict[str, Any] | None:
    """Object metadata, or None if the object does not exist."""
    return _call("stat_object", bucket, key)


def read_range(bucket: str, key: str, start: int, end: int | None) -> bytes:
    """Read bytes [start, end] inclusive. end=None reads to the end of the object."""
    return _call("read_range", bucket, key, start, end)


def read_text(bucket: str, key: str) -> str:
    """Read a whole object as UTF-8 text, replacing undecodable bytes."""
    return _call("read_text", bucket, key)


def download(bucket: str, key: str, local_path: str) -> None:
    """Stream a whole object to local_path."""
    _call("download", bucket, key, local_path)


# ===== JSON backend (google-cloud-storage) =====


def _json_client() -> storage.Client:
    """Build a storage.Client, tolerating an undeterminable project.

    ``storage.Client()`` raises ``EnvironmentError: Project was not passed and
    could not be determined from the environment`` when ADC is a user
    credential and no gcloud config is readable. Read-only operations on
    buckets that are not requester-pays never use the project, so a placeholder
    is harmless and beats failing outright.
    """
    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if project:
        return storage.Client(project=project)
    try:
        return storage.Client()
    except OSError as exc:  # EnvironmentError is an alias of OSError
        logger.info(
            "No GCS project could be determined (%s); continuing with a placeholder. "
            "Set GOOGLE_CLOUD_PROJECT to silence this.",
            exc,
        )
        return storage.Client(project=_PLACEHOLDER_PROJECT)


def _json_list_objects(
    bucket: str, prefix: str, max_results: int, delimiter: str | None
) -> dict[str, Any]:
    client = _json_client()
    iterator = client.list_blobs(
        bucket,
        prefix=prefix if prefix else None,
        max_results=max_results + 1,
        delimiter=delimiter,
    )
    objects: list[dict[str, Any]] = []
    truncated = False
    for blob in iterator:
        if len(objects) >= max_results:
            truncated = True
            break
        objects.append(
            {
                "name": blob.name,
                "size": blob.size,
                "content_type": blob.content_type,
                "updated": blob.updated.isoformat() if blob.updated else None,
                "md5_hash": blob.md5_hash,
            }
        )
    prefixes = sorted(iterator.prefixes) if delimiter else []
    return {"objects": objects, "prefixes": list(prefixes), "truncated": truncated}


def _json_stat_object(bucket: str, key: str) -> dict[str, Any] | None:
    blob = _json_client().bucket(bucket).get_blob(key)
    if blob is None:
        return None
    return {
        "name": blob.name,
        "size": blob.size,
        "content_type": blob.content_type,
        "md5_hash": blob.md5_hash,
        "crc32c": blob.crc32c,
        "time_created": blob.time_created.isoformat() if blob.time_created else None,
        "updated": blob.updated.isoformat() if blob.updated else None,
        "generation": blob.generation,
        "metageneration": blob.metageneration,
        "storage_class": blob.storage_class,
        "custom_metadata": blob.metadata or {},
    }


def _json_read_range(bucket: str, key: str, start: int, end: int | None) -> bytes:
    blob = _json_client().bucket(bucket).blob(key)
    return blob.download_as_bytes(start=start, end=end)


def _json_read_text(bucket: str, key: str) -> str:
    return _json_client().bucket(bucket).blob(key).download_as_text()


def _json_download(bucket: str, key: str, local_path: str) -> None:
    _json_client().bucket(bucket).blob(key).download_to_filename(local_path)


# ===== XML backend (per-bucket virtual-hosted hostnames) =====


def _xml_token() -> str:
    global _credentials
    if _credentials is None:
        _credentials, _ = google.auth.default(scopes=[_READ_SCOPE])
    if not _credentials.valid:
        _credentials.refresh(google.auth.transport.requests.Request())
    return str(_credentials.token)


def _xml_session() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
    return _session


def _xml_host(bucket: str) -> str:
    return f"{bucket}.storage.googleapis.com"


def _xml_request(
    method: str,
    bucket: str,
    key: str = "",
    *,
    params: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
    stream: bool = False,
) -> requests.Response:
    url = f"https://{_xml_host(bucket)}/{urllib.parse.quote(key, safe='/')}"
    request_headers = {
        "Authorization": f"Bearer {_xml_token()}",
        "x-goog-api-version": "2",
    }
    if headers:
        request_headers.update(headers)
    try:
        return _xml_session().request(
            method, url, params=params, headers=request_headers, stream=stream, timeout=_TIMEOUT
        )
    except requests.exceptions.ProxyError as exc:
        raise RuntimeError(
            f"Could not reach {_xml_host(bucket)} through the sandbox proxy ({exc}). "
            f"Under Claude Science, add '{_xml_host(bucket)}' to this connector's "
            "'Allowed domains' setting, then restart the server."
        ) from exc


def _xml_raise_for_status(
    response: requests.Response, bucket: str, key: str, read_body: bool = True
) -> None:
    """Translate a non-success XML API status into a GCS exception."""
    status = response.status_code
    if status in (200, 206):
        return
    uri = f"gs://{bucket}/{key}" if key else f"gs://{bucket}"
    # Reading .text would consume a streamed body, so skip it for downloads.
    detail = (response.text or "")[:400].strip() if read_body else ""
    if status == 404:
        raise NotFound(f"{uri} not found")
    if status in (401, 403):
        raise Forbidden(f"Access denied to {uri}. {detail}".strip())
    raise RuntimeError(f"HTTP {status} from {_xml_host(bucket)} for {uri}. {detail}".strip())


def _xml_checked(
    method: str,
    bucket: str,
    key: str = "",
    *,
    params: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
    stream: bool = False,
) -> requests.Response:
    """Issue a request, raising NotFound / Forbidden / RuntimeError on failure."""
    response = _xml_request(method, bucket, key, params=params, headers=headers, stream=stream)
    _xml_raise_for_status(response, bucket, key, read_body=not stream)
    return response


def _xml_text(node: ET.Element | None, path: str) -> str | None:
    if node is None:
        return None
    found = node.find(path, _XML_NS)
    return found.text if found is not None else None


def _etag_to_md5(etag: str | None) -> str | None:
    """Convert an XML-API ETag to the JSON API's base64 md5, when it is one.

    For single-part uploads the ETag is the hex md5; for composite and
    multipart objects it is not an md5 at all, in which case there is nothing
    to report.
    """
    if not etag:
        return None
    value = etag.strip().strip('"')
    if len(value) != 32:
        return None
    try:
        return base64.b64encode(bytes.fromhex(value)).decode("ascii")
    except (ValueError, binascii.Error):
        return None


def _parse_goog_hash(header: str | None) -> dict[str, str]:
    """Parse `x-goog-hash: crc32c=AAAA==,md5=BBBB==` into a dict."""
    hashes: dict[str, str] = {}
    for part in (header or "").split(","):
        name, _, value = part.strip().partition("=")
        if name and value:
            hashes[name.strip().lower()] = value.strip()
    return hashes


def _http_date_to_iso(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return email.utils.parsedate_to_datetime(value).isoformat()
    except (TypeError, ValueError):
        return value


def _int_or_none(value: str | None) -> int | None:
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def _xml_list_objects(
    bucket: str, prefix: str, max_results: int, delimiter: str | None
) -> dict[str, Any]:
    objects: list[dict[str, Any]] = []
    prefixes: list[str] = []
    truncated = False
    continuation: str | None = None

    while True:
        params = {"list-type": "2", "max-keys": str(_XML_MAX_KEYS)}
        if prefix:
            params["prefix"] = prefix
        if delimiter:
            params["delimiter"] = delimiter
        if continuation:
            params["continuation-token"] = continuation

        root = ET.fromstring(_xml_checked("GET", bucket, params=params).content)

        for node in root.findall("s3:Contents", _XML_NS):
            if len(objects) >= max_results:
                truncated = True
                break
            objects.append(
                {
                    "name": _xml_text(node, "s3:Key"),
                    "size": _int_or_none(_xml_text(node, "s3:Size")),
                    # A list response carries no content type; the JSON API's
                    # listing does. Callers that need it call stat_object.
                    "content_type": None,
                    "updated": _xml_text(node, "s3:LastModified"),
                    "md5_hash": _etag_to_md5(_xml_text(node, "s3:ETag")),
                }
            )

        for node in root.findall("s3:CommonPrefixes", _XML_NS):
            found = _xml_text(node, "s3:Prefix")
            if found and found not in prefixes:
                prefixes.append(found)

        if truncated:
            break
        continuation = _xml_text(root, "s3:NextContinuationToken")
        more_pages = (_xml_text(root, "s3:IsTruncated") or "false").lower() == "true"
        if not (more_pages and continuation):
            break
        if len(objects) >= max_results:
            truncated = True
            break

    return {"objects": objects, "prefixes": sorted(prefixes), "truncated": truncated}


def _xml_stat_object(bucket: str, key: str) -> dict[str, Any] | None:
    response = _xml_request("HEAD", bucket, key)
    if response.status_code == 404:
        return None
    _xml_raise_for_status(response, bucket, key)

    headers = response.headers
    hashes = _parse_goog_hash(headers.get("x-goog-hash"))
    size = headers.get("x-goog-stored-content-length") or headers.get("Content-Length")
    return {
        "name": key,
        "size": _int_or_none(size),
        "content_type": headers.get("Content-Type"),
        "md5_hash": hashes.get("md5"),
        "crc32c": hashes.get("crc32c"),
        # The XML API reports only Last-Modified, never a creation time.
        "time_created": None,
        "updated": _http_date_to_iso(headers.get("Last-Modified")),
        "generation": _int_or_none(headers.get("x-goog-generation")),
        "metageneration": _int_or_none(headers.get("x-goog-metageneration")),
        "storage_class": headers.get("x-goog-storage-class"),
        "custom_metadata": {
            name[len("x-goog-meta-") :]: value
            for name, value in headers.items()
            if name.lower().startswith("x-goog-meta-")
        },
    }


def _xml_read_range(bucket: str, key: str, start: int, end: int | None) -> bytes:
    headers = {}
    if start or end is not None:
        headers["Range"] = f"bytes={start}-" if end is None else f"bytes={start}-{end}"
    response = _xml_request("GET", bucket, key, headers=headers or None)
    if response.status_code == 416:
        return b""  # range starts past the end of the object
    _xml_raise_for_status(response, bucket, key)
    return bytes(response.content)


def _xml_read_text(bucket: str, key: str) -> str:
    return _xml_read_range(bucket, key, 0, None).decode("utf-8", errors="replace")


def _xml_download(bucket: str, key: str, local_path: str) -> None:
    response = _xml_checked("GET", bucket, key, stream=True)
    with open(local_path, "wb") as handle:
        for chunk in response.iter_content(chunk_size=_CHUNK):
            if chunk:
                handle.write(chunk)


_IMPL: dict[str, dict[str, Any]] = {
    "json": {
        "list_objects": _json_list_objects,
        "stat_object": _json_stat_object,
        "read_range": _json_read_range,
        "read_text": _json_read_text,
        "download": _json_download,
    },
    "xml": {
        "list_objects": _xml_list_objects,
        "stat_object": _xml_stat_object,
        "read_range": _xml_read_range,
        "read_text": _xml_read_text,
        "download": _xml_download,
    },
}
