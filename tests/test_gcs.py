"""Tests for the two GCS backends in terra_mcp.gcs.

The XML backend exists because Claude Science's sandbox permanently blocks
storage.googleapis.com, so these tests drive it against canned XML API
responses rather than a real bucket. The JSON backend is exercised through the
server tools in test_server.py; here we only cover its project fallback.
"""

import pytest
import requests
from google.cloud.exceptions import Forbidden, NotFound
from requests.structures import CaseInsensitiveDict

from terra_mcp import gcs

NS = 'xmlns="http://doc.s3.amazonaws.com/2006-03-01"'
MD5_HEX = "0cc175b9c0f1b6a831c399e269772661"  # md5("a")
MD5_B64 = "DMF1ucDxtqgxw5niaXcmYQ=="


class FakeRaw:
    """Stand-in for urllib3's raw stream, which the backend reads undecoded."""

    def __init__(self, chunks):
        self._chunks = list(chunks)
        self.decode_content_args = []

    def read(self, decode_content=True):
        self.decode_content_args.append(decode_content)
        data = b"".join(self._chunks)
        self._chunks = []
        return data

    def stream(self, chunk_size=None, decode_content=True):
        self.decode_content_args.append(decode_content)
        chunks, self._chunks = self._chunks, []
        yield from chunks


class FakeResponse:
    """Minimal stand-in for requests.Response."""

    def __init__(self, status_code=200, content=b"", headers=None, chunks=None):
        self.status_code = status_code
        self.content = content
        self.headers = CaseInsensitiveDict(headers or {})
        self._chunks = chunks
        self.raw = FakeRaw(chunks if chunks is not None else [content])
        self.closed = False

    @property
    def text(self):
        return self.content.decode("utf-8", errors="replace")

    def iter_content(self, chunk_size=None):
        yield from (self._chunks if self._chunks is not None else [self.content])

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.closed = True
        return False


class FakeSession:
    def __init__(self, *responses):
        self.queued = list(responses)
        self.calls = []

    def request(self, method, url, params=None, headers=None, stream=False, timeout=None):
        self.calls.append(
            {"method": method, "url": url, "params": params, "headers": headers, "stream": stream}
        )
        if not self.queued:
            raise AssertionError(f"unexpected extra request: {method} {url}")
        response = self.queued.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


@pytest.fixture
def xml(monkeypatch):
    """Force the XML backend with a stub session and no real token fetch."""
    monkeypatch.setattr(gcs, "_xml_token", lambda: "test-token")
    gcs.set_backend("xml")

    def install(*responses):
        session = FakeSession(*responses)
        monkeypatch.setattr(gcs, "_session", session)
        return session

    yield install
    gcs.set_backend("auto")
    gcs._session = None


def listing(contents=(), prefixes=(), truncated=False, token=None):
    body = [f"<?xml version='1.0' encoding='UTF-8'?><ListBucketResult {NS}>"]
    body.append(f"<IsTruncated>{'true' if truncated else 'false'}</IsTruncated>")
    if token:
        body.append(f"<NextContinuationToken>{token}</NextContinuationToken>")
    for key, size in contents:
        body.append(
            f"<Contents><Key>{key}</Key><Size>{size}</Size>"
            f"<LastModified>2026-10-01T12:00:00.000Z</LastModified>"
            f'<ETag>"{MD5_HEX}"</ETag></Contents>'
        )
    for prefix in prefixes:
        body.append(f"<CommonPrefixes><Prefix>{prefix}</Prefix></CommonPrefixes>")
    body.append("</ListBucketResult>")
    return FakeResponse(content="".join(body).encode())


# ===== XML listing =====


class TestXmlList:
    def test_parses_objects_and_converts_etag_to_md5(self, xml):
        xml(listing(contents=[("logs/a.log", 10)]))

        result = gcs.list_objects("fc-bucket", "logs/", 100, None)

        assert result["truncated"] is False
        assert result["objects"] == [
            {
                "name": "logs/a.log",
                "size": 10,
                "content_type": None,
                "updated": "2026-10-01T12:00:00.000Z",
                "md5_hash": MD5_B64,
            }
        ]

    def test_sends_prefix_and_list_type_v2(self, xml):
        session = xml(listing(contents=[("logs/a.log", 1)]))

        gcs.list_objects("fc-bucket", "logs/", 100, None)

        call = session.calls[0]
        assert call["url"] == "https://fc-bucket.storage.googleapis.com/"
        assert call["params"]["list-type"] == "2"
        assert call["params"]["prefix"] == "logs/"
        assert "delimiter" not in call["params"]
        assert call["headers"]["Authorization"] == "Bearer test-token"

    def test_follows_continuation_token(self, xml):
        session = xml(
            listing(contents=[("a", 1), ("b", 2)], truncated=True, token="TOKEN1"),
            listing(contents=[("c", 3)]),
        )

        result = gcs.list_objects("fc-bucket", "", 100, None)

        assert [o["name"] for o in result["objects"]] == ["a", "b", "c"]
        assert result["truncated"] is False
        assert session.calls[1]["params"]["continuation-token"] == "TOKEN1"

    def test_truncates_at_max_results_within_a_page(self, xml):
        xml(listing(contents=[("a", 1), ("b", 2), ("c", 3)]))

        result = gcs.list_objects("fc-bucket", "", 2, None)

        assert [o["name"] for o in result["objects"]] == ["a", "b"]
        assert result["truncated"] is True

    def test_truncates_when_more_pages_remain_at_max_results(self, xml):
        xml(listing(contents=[("a", 1), ("b", 2)], truncated=True, token="T"))

        result = gcs.list_objects("fc-bucket", "", 2, None)

        assert result["truncated"] is True

    def test_delimiter_returns_common_prefixes(self, xml):
        session = xml(listing(contents=[("top.txt", 1)], prefixes=["sub/", "other/"]))

        result = gcs.list_objects("fc-bucket", "", 100, "/")

        assert result["prefixes"] == ["other/", "sub/"]
        assert session.calls[0]["params"]["delimiter"] == "/"

    def test_composite_etag_yields_no_md5(self, xml):
        body = (
            f"<?xml version='1.0' encoding='UTF-8'?><ListBucketResult {NS}>"
            "<IsTruncated>false</IsTruncated>"
            "<Contents><Key>big.bam</Key><Size>5</Size>"
            "<LastModified>2026-10-01T12:00:00.000Z</LastModified>"
            '<ETag>"abc-12"</ETag></Contents></ListBucketResult>'
        )
        xml(FakeResponse(content=body.encode()))

        result = gcs.list_objects("fc-bucket", "", 100, None)

        assert result["objects"][0]["md5_hash"] is None


# ===== XML metadata, reads, downloads =====


class TestXmlObjectOps:
    def test_stat_maps_headers(self, xml):
        session = xml(
            FakeResponse(
                headers={
                    "Content-Length": "40",
                    "x-goog-stored-content-length": "42",
                    "Content-Type": "text/plain",
                    "Last-Modified": "Thu, 01 Oct 2026 12:00:00 GMT",
                    "x-goog-hash": f"crc32c=AAAAAA==,md5={MD5_B64}",
                    "x-goog-generation": "17",
                    "x-goog-metageneration": "2",
                    "x-goog-storage-class": "STANDARD",
                    "x-goog-meta-sample": "NA12878",
                }
            )
        )

        info = gcs.stat_object("fc-bucket", "path/file.txt")

        assert session.calls[0]["method"] == "HEAD"
        assert info["size"] == 42  # stored length wins over a transcoded length
        assert info["content_type"] == "text/plain"
        assert info["md5_hash"] == MD5_B64
        assert info["crc32c"] == "AAAAAA=="
        assert info["generation"] == 17
        assert info["metageneration"] == 2
        assert info["storage_class"] == "STANDARD"
        assert info["custom_metadata"] == {"sample": "NA12878"}
        assert info["updated"].startswith("2026-10-01T12:00:00")
        assert info["time_created"] is None  # not reported by the XML API

    def test_stat_missing_object_returns_none(self, xml):
        xml(FakeResponse(status_code=404))

        assert gcs.stat_object("fc-bucket", "missing.txt") is None

    def test_read_range_sends_inclusive_range_header(self, xml):
        session = xml(FakeResponse(status_code=206, content=b"partial"))

        data = gcs.read_range("fc-bucket", "f.txt", 10, 16)

        assert data == b"partial"
        assert session.calls[0]["headers"]["Range"] == "bytes=10-16"

    def test_read_whole_object_sends_no_range_header(self, xml):
        session = xml(FakeResponse(content=b"all of it"))

        assert gcs.read_range("fc-bucket", "f.txt", 0, None) == b"all of it"
        assert "Range" not in session.calls[0]["headers"]

    def test_range_past_end_of_object_is_empty(self, xml):
        xml(FakeResponse(status_code=416))

        assert gcs.read_range("fc-bucket", "f.txt", 99, 199) == b""

    def test_read_text_replaces_undecodable_bytes(self, xml):
        xml(FakeResponse(content=b"log line \xff\xfe done"))

        assert gcs.read_text("fc-bucket", "log.txt") == "log line �� done"

    def test_download_streams_chunks_to_disk(self, xml, tmp_path):
        session = xml(FakeResponse(chunks=[b"abc", b"", b"def"]))
        dest = tmp_path / "out.bin"

        gcs.download("fc-bucket", "f.bin", str(dest))

        assert dest.read_bytes() == b"abcdef"
        assert session.calls[0]["stream"] is True

    def test_keys_are_url_quoted(self, xml):
        session = xml(FakeResponse(content=b""))

        gcs.read_range("fc-bucket", "a dir/f#1.txt", 0, None)

        assert session.calls[0]["url"].endswith("/a%20dir/f%231.txt")


class TestXmlErrors:
    def test_404_raises_not_found(self, xml):
        xml(FakeResponse(status_code=404, content=b"<Error>NoSuchKey</Error>"))

        with pytest.raises(NotFound, match="gs://fc-bucket/missing.txt"):
            gcs.read_range("fc-bucket", "missing.txt", 0, None)

    def test_403_raises_forbidden_with_detail(self, xml):
        xml(FakeResponse(status_code=403, content=b"<Error>AccessDenied</Error>"))

        with pytest.raises(Forbidden, match="AccessDenied"):
            gcs.list_objects("fc-bucket", "", 10, None)

    def test_other_status_raises_runtime_error(self, xml):
        xml(FakeResponse(status_code=500, content=b"oops"))

        with pytest.raises(RuntimeError, match="HTTP 500"):
            gcs.list_objects("fc-bucket", "", 10, None)

    def test_proxy_error_names_the_host_to_allowlist(self, xml):
        xml(requests.exceptions.ProxyError("Tunnel connection failed: 403 Forbidden"))

        with pytest.raises(RuntimeError, match="fc-bucket.storage.googleapis.com"):
            gcs.list_objects("fc-bucket", "", 10, None)


# ===== Backend selection =====


class TestBackendSelection:
    def setup_method(self):
        gcs.set_backend("auto")

    def teardown_method(self):
        gcs.set_backend("auto")
        gcs._session = None

    def test_auto_falls_back_to_xml_when_the_json_host_is_blocked(self, monkeypatch):
        monkeypatch.setattr(gcs, "_xml_token", lambda: "test-token")
        monkeypatch.setattr(
            gcs, "_session", FakeSession(FakeResponse(headers={"Content-Length": "5"}))
        )

        def blocked(*_args, **_kwargs):
            raise requests.exceptions.ProxyError(
                "Tunnel connection failed: 403 Forbidden (host storage.googleapis.com "
                "not on the allowlist)"
            )

        monkeypatch.setitem(gcs._IMPL["json"], "stat_object", blocked)

        info = gcs.stat_object("fc-bucket", "f.txt")

        assert info["size"] == 5
        assert gcs.active_backend() == "xml"  # latched for the rest of the process

    def test_auto_keeps_json_when_gcs_answers_with_a_denial(self, monkeypatch):
        def denied(*_args, **_kwargs):
            raise Forbidden("real permission problem")

        monkeypatch.setitem(gcs._IMPL["json"], "stat_object", denied)

        with pytest.raises(Forbidden):
            gcs.stat_object("fc-bucket", "f.txt")
        assert gcs.active_backend() == "json"

    def test_auto_does_not_fall_back_on_an_unrelated_error(self, monkeypatch):
        def broken(*_args, **_kwargs):
            raise ValueError("bad argument")

        monkeypatch.setitem(gcs._IMPL["json"], "stat_object", broken)

        with pytest.raises(ValueError):
            gcs.stat_object("fc-bucket", "f.txt")

    def test_explicit_backend_is_not_probed(self):
        gcs.set_backend("xml")
        assert gcs.active_backend() == "xml"
        gcs.set_backend("json")
        assert gcs.active_backend() == "json"

    def test_unknown_backend_rejected(self):
        with pytest.raises(ValueError, match="Unknown GCS backend"):
            gcs.set_backend("s3")


class TestJsonClientProject:
    def test_env_project_is_used_directly(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "my-project")
        seen = []
        monkeypatch.setattr(gcs.storage, "Client", lambda project=None: seen.append(project))

        gcs._json_client()

        assert seen == ["my-project"]

    def test_placeholder_project_when_none_can_be_determined(self, monkeypatch):
        monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
        seen = []

        def client(project=None):
            seen.append(project)
            if project is None:
                raise OSError("Project was not passed and could not be determined")
            return "client"

        monkeypatch.setattr(gcs.storage, "Client", client)

        assert gcs._json_client() == "client"
        assert seen == [None, gcs._PLACEHOLDER_PROJECT]


# ===== Server tools driven through the XML backend =====


class TestToolsOnXmlBackend:
    """The tools, not just the backend module, must work when XML is in use.

    This is the Claude Science path end to end: stat via HEAD, then a ranged
    GET, with no traffic to storage.googleapis.com.
    """

    @pytest.mark.asyncio
    async def test_read_gcs_object(self, xml):
        from unittest.mock import AsyncMock

        from terra_mcp import server as terra_server

        text = "hello, world\n"
        session = xml(
            FakeResponse(headers={"Content-Length": str(len(text)), "Content-Type": "text/plain"}),
            FakeResponse(status_code=206, content=text.encode()),
        )

        result = await terra_server.read_gcs_object("gs://fc-bucket/f.txt", AsyncMock())

        assert result["content"] == text
        assert result["encoding"] == "utf-8"
        assert result["content_type"] == "text/plain"
        assert result["truncated"] is False
        assert [c["method"] for c in session.calls] == ["HEAD", "GET"]

    @pytest.mark.asyncio
    async def test_workflow_log_fetch(self, xml):
        from unittest.mock import AsyncMock

        from terra_mcp import server as terra_server

        xml(FakeResponse(content=b"task failed: exit 1\n"))

        content = await terra_server._fetch_gcs_log("gs://fc-bucket/logs/stderr", AsyncMock())

        assert content == "task failed: exit 1\n"

    @pytest.mark.asyncio
    async def test_access_denied_names_the_host_to_allowlist(self, xml):
        from unittest.mock import AsyncMock

        from fastmcp.exceptions import ToolError

        from terra_mcp import server as terra_server

        xml(FakeResponse(status_code=403, content=b"<Error>AccessDenied</Error>"))

        with pytest.raises(ToolError, match="fc-bucket.storage.googleapis.com"):
            await terra_server.list_gcs_objects("gs://fc-bucket/prefix", AsyncMock())


class TestParsers:
    def test_etag_of_md5_length_but_not_hex_yields_no_md5(self):
        assert gcs._etag_to_md5('"' + "z" * 32 + '"') is None

    def test_malformed_header_values_degrade_quietly(self):
        assert gcs._int_or_none("not-a-number") is None
        assert gcs._int_or_none(None) is None
        assert gcs._http_date_to_iso("yesterday") == "yesterday"
        assert gcs._http_date_to_iso(None) is None

    def test_allowlist_refusal_is_recognised_without_a_requests_exception(self):
        """The sandbox surfaces the refusal as a plain OSError from the proxy."""
        refusal = OSError(
            "Tunnel connection failed: 403 Forbidden "
            "(host storage.googleapis.com not on the allowlist)"
        )
        assert gcs._looks_unreachable(refusal) is True
        assert gcs._looks_unreachable(ValueError("unrelated")) is False

    def test_unreachable_detection_follows_the_exception_chain(self):
        try:
            try:
                raise OSError("host fc-x.storage.googleapis.com not on the allowlist")
            except OSError as inner:
                raise RuntimeError("wrapped") from inner
        except RuntimeError as outer:
            assert gcs._looks_unreachable(outer) is True


# ===== Hardening from PR review =====


class TestBucketValidation:
    """A bucket name becomes a hostname on the XML backend, so it is untrusted input."""

    @pytest.mark.parametrize(
        "bucket",
        [
            "evil.example?",  # query delimiter: host becomes evil.example
            "evil.example#",
            "evil.example/x",
            "evil.example:8080",
            "evil.example@attacker",
            "UPPER-CASE",
            "sp ace",
            "ab",  # too short
            "-leading-hyphen",
            "trailing-dot.",
            "",
        ],
    )
    def test_rejects_names_that_could_redirect_the_request(self, bucket):
        with pytest.raises(ValueError, match="Invalid GCS bucket name"):
            gcs.validate_bucket(bucket)

    @pytest.mark.parametrize(
        "bucket",
        [
            "fc-11111111-2222-3333-4444-555555555555",
            "my-bucket",
            "my.domain.bucket.example.com",
            "with_underscores",
            "abc",
        ],
    )
    def test_accepts_real_bucket_names(self, bucket):
        assert gcs.validate_bucket(bucket) == bucket

    def test_no_token_is_minted_for_a_rejected_bucket(self, monkeypatch):
        """Validation must happen before the bearer token exists, not after."""
        minted = []
        monkeypatch.setattr(gcs, "_xml_token", lambda: minted.append(1) or "tok")
        monkeypatch.setattr(gcs, "_session", FakeSession())
        gcs.set_backend("xml")
        try:
            with pytest.raises(ValueError, match="Invalid GCS bucket name"):
                gcs.read_range("evil.example?", "f.txt", 0, None)
        finally:
            gcs.set_backend("auto")
            gcs._session = None
        assert minted == []

    @pytest.mark.asyncio
    async def test_parse_gcs_uri_rejects_a_crafted_bucket(self):
        from fastmcp.exceptions import ToolError

        from terra_mcp.server import _parse_gcs_uri

        with pytest.raises(ToolError, match="Invalid GCS bucket name"):
            _parse_gcs_uri("gs://attacker.example?/file.txt")


class TestStoredBytesNotDecompressed:
    """Ranged reads and downloads must move stored bytes, not expanded ones."""

    def test_range_read_consumes_the_undecoded_stream(self, xml):
        session = xml(FakeResponse(status_code=206, content=b"stored-bytes"))

        data = gcs.read_range("fc-bucket", "f.gz", 0, 11)

        assert data == b"stored-bytes"
        assert session.queued == []
        # gzip stays acceptable so GCS does not decompressively transcode,
        # and the body is read without decoding
        assert session.calls[0]["headers"]["Accept-Encoding"] == "gzip"
        assert session.calls[0]["stream"] is True

    def test_download_writes_the_undecoded_stream(self, xml, tmp_path):
        session = xml(FakeResponse(chunks=[b"ab", b"cd"]))
        dest = tmp_path / "o.gz"

        gcs.download("fc-bucket", "f.gz", str(dest))

        assert dest.read_bytes() == b"abcd"
        assert session.calls[0]["headers"]["Accept-Encoding"] == "gzip"

    def test_read_text_still_decodes_for_logs(self, xml):
        session = xml(FakeResponse(content=b"task failed\n"))

        assert gcs.read_text("fc-bucket", "logs/stderr") == "task failed\n"
        # not a raw read: a gzip-encoded log should arrive expanded
        assert session.calls[0].get("stream") is False


class TestGenerationPinning:
    """stat_object reports a generation; the transfer must use that same version."""

    def test_range_read_pins_the_generation(self, xml):
        session = xml(FakeResponse(status_code=206, content=b"x"))

        gcs.read_range("fc-bucket", "f.txt", 0, 0, 1766)

        assert session.calls[0]["params"] == {"generation": "1766"}

    def test_download_pins_the_generation(self, xml, tmp_path):
        session = xml(FakeResponse(content=b"x"))

        gcs.download("fc-bucket", "f.txt", str(tmp_path / "f"), 1766)

        assert session.calls[0]["params"] == {"generation": "1766"}

    def test_no_generation_sends_no_parameter(self, xml):
        session = xml(FakeResponse(status_code=206, content=b"x"))

        gcs.read_range("fc-bucket", "f.txt", 0, 0)

        assert session.calls[0]["params"] is None

    def test_json_backend_pins_the_generation(self, monkeypatch):
        seen = {}

        class FakeBucket:
            def blob(self, key, generation=None):
                seen["generation"] = generation
                blob = type("B", (), {})()
                blob.download_as_bytes = lambda **kw: b"x"
                return blob

        class FakeClient:
            def bucket(self, name):
                return FakeBucket()

        monkeypatch.setattr(gcs, "_json_client", FakeClient)
        gcs.set_backend("json")
        try:
            assert gcs.read_range("fc-bucket", "f.txt", 0, 0, 99) == b"x"
        finally:
            gcs.set_backend("auto")
        assert seen["generation"] == 99


class TestDownloadIsAtomic:
    """A failed transfer must not leave anything at the destination."""

    def _info(self, size=100):
        return {
            "name": "f.bam",
            "size": size,
            "content_type": "application/octet-stream",
            "md5_hash": "abc==",
            "crc32c": "def==",
            "time_created": None,
            "updated": None,
            "generation": 7,
            "metageneration": 1,
            "storage_class": "STANDARD",
            "custom_metadata": {},
        }

    @pytest.mark.asyncio
    async def test_stream_failure_leaves_no_partial_file(self, tmp_path, monkeypatch):
        from unittest.mock import AsyncMock

        from fastmcp.exceptions import ToolError

        from terra_mcp import server as terra_server

        def write_some_then_die(bucket, key, path, generation=None):
            with open(path, "wb") as handle:
                handle.write(b"half of it")
            raise ConnectionError("stream died mid-transfer")

        monkeypatch.setitem(gcs._IMPL["xml"], "stat_object", lambda b, k: self._info())
        monkeypatch.setitem(gcs._IMPL["xml"], "download", write_some_then_die)
        gcs.set_backend("xml")
        dest = tmp_path / "out.bam"
        try:
            with pytest.raises(ToolError, match="stream died"):
                await terra_server.download_gcs_file("gs://fc-bucket/f.bam", str(dest), AsyncMock())
        finally:
            gcs.set_backend("auto")

        assert not dest.exists()
        assert list(tmp_path.iterdir()) == []  # no .partial left behind either

    @pytest.mark.asyncio
    async def test_short_transfer_leaves_no_partial_file(self, tmp_path, monkeypatch):
        from unittest.mock import AsyncMock

        from fastmcp.exceptions import ToolError

        from terra_mcp import server as terra_server

        def write_too_few_bytes(bucket, key, path, generation=None):
            with open(path, "wb") as handle:
                handle.write(b"short")

        monkeypatch.setitem(gcs._IMPL["xml"], "stat_object", lambda b, k: self._info())
        monkeypatch.setitem(gcs._IMPL["xml"], "download", write_too_few_bytes)
        gcs.set_backend("xml")
        dest = tmp_path / "out.bam"
        try:
            with pytest.raises(ToolError, match="does not match"):
                await terra_server.download_gcs_file("gs://fc-bucket/f.bam", str(dest), AsyncMock())
        finally:
            gcs.set_backend("auto")

        assert not dest.exists()
        assert list(tmp_path.iterdir()) == []

    @pytest.mark.asyncio
    async def test_successful_transfer_lands_at_the_destination(self, tmp_path, monkeypatch):
        from unittest.mock import AsyncMock

        from terra_mcp import server as terra_server

        payload = b"y" * 100

        def write_all(bucket, key, path, generation=None):
            with open(path, "wb") as handle:
                handle.write(payload)

        monkeypatch.setitem(gcs._IMPL["xml"], "stat_object", lambda b, k: self._info())
        monkeypatch.setitem(gcs._IMPL["xml"], "download", write_all)
        gcs.set_backend("xml")
        dest = tmp_path / "out.bam"
        try:
            result = await terra_server.download_gcs_file(
                "gs://fc-bucket/f.bam", str(dest), AsyncMock()
            )
        finally:
            gcs.set_backend("auto")

        assert dest.read_bytes() == payload
        assert result["bytes_downloaded"] == 100
        assert [p.name for p in tmp_path.iterdir()] == ["out.bam"]
