"""Offline regressions for S1-S5; also runnable with stdlib unittest."""

import asyncio
import gzip
import logging
from pathlib import Path
import re
import socket
import ssl
import tempfile
import time
import traceback
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import httpx

from src.core.llm.base import LLMError, SlotModel
from src.core.llm.gateway import LLMGateway
from src.core.llm.genai_client import GenAIClient
from src.core.llm.redaction import redact_diagnostic
from src.handlers.discord.ui import EndpointConfigFlow
from src.services.indexing.parser import FileParserService
from src.tools.builtin import vision
from src.tools.search.providers import fetcher
from src.tools.search.url_safety import build_pinned_request


def dns_answer(ip):
    return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (ip, 0))]


class Body:
    def __init__(self, chunks, delay=0):
        self.chunks = chunks
        self.delay = delay
        self.consumed = 0

    async def iter_chunked(self, size):
        for chunk in self.chunks:
            if self.delay:
                await asyncio.sleep(self.delay)
            self.consumed += 1
            yield chunk


class Response:
    def __init__(self, chunks=(), *, headers=None, status=200, delay=0):
        self.status = status
        self.headers = headers or {}
        self.charset = None
        self.content = Body(chunks, delay)
        self.closed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        self.closed = True

    async def read(self):
        # Old implementations buffer the whole response; streaming regressions
        # verify that later chunks are never consumed after the cap is reached.
        return b"".join(self.content.chunks)


class SecurityNetworkTests(unittest.IsolatedAsyncioTestCase):
    def sessions(self, responses, calls=None):
        responses = iter(responses)
        calls = calls if calls is not None else []

        class Session:
            def __init__(self, **kwargs):
                self.connector = kwargs.get("connector")
                calls.append(kwargs)

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                if self.connector:
                    await self.connector.close()

            def get(self, url, **kwargs):
                calls[-1]["url"] = url
                calls[-1]["request"] = kwargs
                return next(responses)

        return Session

    async def test_s1_vision_pins_each_validated_redirect(self):
        calls = []
        resolvers = []
        original = build_pinned_request

        def capture(url, ip):
            result = original(url, ip)
            resolvers.append(result[1]._resolver)
            return result

        first = Response(headers={"Location": "https://other.org/final.png"}, status=302)
        final = Response([b"image"], headers={"Content-Type": "image/png"})
        with patch.object(vision.aiohttp, "ClientSession", self.sessions([first, final], calls)), \
                patch.object(vision, "build_pinned_request", capture), \
                patch("socket.getaddrinfo", side_effect=[dns_answer("8.8.8.8"), dns_answer("1.1.1.1")]) as dns:
            data, _, error = await vision.VisionTool()._download_image("https://images.org/start.png")
        self.assertEqual(data, b"image")
        self.assertIsNone(error)
        self.assertEqual(dns.call_count, 2)
        self.assertEqual(len(resolvers), 2)
        # DNS has now rebound; transport resolution must use the earlier IPs.
        with patch("socket.getaddrinfo", side_effect=AssertionError("DNS re-resolution")):
            for resolver, host, ip in zip(resolvers, ["images.org", "other.org"], ["8.8.8.8", "1.1.1.1"]):
                self.assertEqual((await resolver.resolve(host, 443))[0]["host"], ip)
        self.assertEqual([c["url"] for c in calls], ["https://images.org/start.png", "https://other.org/final.png"])
        self.assertTrue(first.closed and final.closed)
        self.assertTrue(all(not c["request"]["allow_redirects"] for c in calls))

    async def test_s1_redirect_to_private_address_is_never_requested(self):
        for kind in ("vision", "page"):
            with self.subTest(kind=kind):
                calls = []
                redirect = Response(headers={"Location": "https://private.org/secret"}, status=302)
                with patch("aiohttp.ClientSession", self.sessions([redirect], calls)), \
                        patch("socket.getaddrinfo", side_effect=lambda host, *a, **k: dns_answer(
                            "127.0.0.1" if host == "private.org" else "8.8.8.8"
                        )):
                    if kind == "vision":
                        self.assertIsNone((await vision.VisionTool()._download_image("https://public.org/a.png"))[0])
                    else:
                        self.assertEqual(await fetcher.PageEvidenceFetcher().fetch_page_evidence("https://public.org/"), "")
                self.assertTrue(calls)
                self.assertTrue(all(c["url"].startswith("https://public.org/") for c in calls))

    async def test_s2_transport_uses_pinned_ip_and_original_tls_hostname(self):
        # Intercept immediately before the actual socket/TLS connection. This
        # exercises aiohttp's real resolver and TLS setup without network I/O.
        for kind in ("vision", "page"):
            with self.subTest(kind=kind):
                connections = []

                async def connect(connector, *args, **kwargs):
                    connections.append(kwargs)
                    raise aiohttp.ClientConnectionError("stop before network")

                with patch.object(aiohttp.TCPConnector, "_wrap_create_connection", connect), \
                        patch("socket.getaddrinfo", return_value=dns_answer("8.8.8.8")):
                    if kind == "vision":
                        with self.assertRaises(aiohttp.ClientConnectionError):
                            await vision.VisionTool()._download_image("https://images.org:8443/a.png")
                    else:
                        await fetcher.PageEvidenceFetcher().fetch_page_evidence("https://images.org:8443/article")
                self.assertTrue(connections)
                for conn in connections:
                    self.assertEqual(conn["server_hostname"], "images.org")
                    self.assertTrue(conn["ssl"].check_hostname)
                    self.assertEqual(conn["ssl"].verify_mode, ssl.CERT_REQUIRED)
                    self.assertEqual(conn["addr_infos"][0][4], ("8.8.8.8", 8443))

    async def test_s1_empty_validation_ip_cannot_bypass_transport_validation(self):
        url, connector = build_pinned_request("https://example.com/", "")
        try:
            self.assertEqual(url, "https://example.com/")
            with patch("socket.getaddrinfo", return_value=dns_answer("127.0.0.1")):
                with self.assertRaises(OSError):
                    await connector._resolver.resolve("example.com", 443)
        finally:
            await connector.close()

    async def test_s3_stream_caps_identity_and_gzip_for_both_downloaders(self):
        for kind in ("vision", "page"):
            for encoding in ("identity", "gzip"):
                with self.subTest(kind=kind, encoding=encoding):
                    chunk = gzip.compress(b"x" * 10000) if encoding == "gzip" else b"x" * 65
                    responses = [Response([chunk, b"never read"], headers={
                        "Content-Type": "image/png", "Content-Encoding": encoding,
                        # Compressed and misleading lengths cannot replace a byte cap.
                        "Content-Length": "1",
                    }) for _ in range(2)]
                    calls = []
                    with patch("aiohttp.ClientSession", self.sessions(responses, calls)), \
                            patch("socket.getaddrinfo", return_value=dns_answer("8.8.8.8")), \
                            patch.object(vision, "MAX_IMAGE_BYTES", 64), patch.object(fetcher, "MAX_PAGE_BYTES", 64):
                        if kind == "vision":
                            self.assertIsNone((await vision.VisionTool()._download_image("https://images.org/a.png"))[0])
                        else:
                            self.assertEqual(await fetcher.PageEvidenceFetcher().fetch_page_evidence("https://images.org/"), "")
                    self.assertEqual(responses[0].content.consumed, 1)
                    self.assertTrue(responses[0].closed)
                    self.assertTrue(all(c["auto_decompress"] is False for c in calls))

    async def test_s3_content_length_rejected_before_reading(self):
        for kind in ("vision", "page"):
            with self.subTest(kind=kind):
                responses = [Response([b"unused"], headers={
                    "Content-Type": "image/png", "Content-Length": "999999999",
                }) for _ in range(2)]
                with patch("aiohttp.ClientSession", self.sessions(responses)), \
                        patch("socket.getaddrinfo", return_value=dns_answer("8.8.8.8")):
                    if kind == "vision":
                        self.assertIsNone((await vision.VisionTool()._download_image("https://images.org/a.png"))[0])
                    else:
                        self.assertEqual(await fetcher.PageEvidenceFetcher().fetch_page_evidence("https://images.org/"), "")
                self.assertEqual(responses[0].content.consumed, 0)
                self.assertTrue(responses[0].closed)

    async def test_s3_absolute_deadline_cancels_slow_stream_and_closes_response(self):
        for kind in ("vision", "page"):
            with self.subTest(kind=kind):
                response = Response([b"x"] * 100, headers={"Content-Type": "image/png"}, delay=0.01)
                with patch("aiohttp.ClientSession", self.sessions([response])), \
                        patch("socket.getaddrinfo", return_value=dns_answer("8.8.8.8")), \
                        patch.object(vision, "DOWNLOAD_TOTAL_SECONDS", 0.04), \
                        patch.object(fetcher, "DOWNLOAD_TOTAL_SECONDS", 0.04):
                    started = time.monotonic()
                    if kind == "vision":
                        with self.assertRaises(TimeoutError):
                            await vision.VisionTool()._download_image("https://images.org/a.png")
                    else:
                        self.assertEqual(await fetcher.PageEvidenceFetcher().fetch_page_evidence("https://images.org/"), "")
                    self.assertLess(time.monotonic() - started, 0.5)
                self.assertTrue(response.closed)
                self.assertLess(response.content.consumed, 100)

    async def test_s3_small_compressed_download_still_succeeds(self):
        html = b"<html><body><p>" + b"article content " * 30 + b"</p></body></html>"
        response = Response([gzip.compress(html)], headers={"Content-Encoding": "gzip"})
        with patch("aiohttp.ClientSession", self.sessions([response])), \
                patch("socket.getaddrinfo", return_value=dns_answer("8.8.8.8")):
            self.assertIn("article content", await fetcher.PageEvidenceFetcher().fetch_page_evidence("https://public.org/"))


class ParserSecurityTests(unittest.TestCase):
    def test_s4_repeated_unclosed_comments_have_no_quadratic_regex(self):
        parser = FileParserService()
        # Catch use of the vulnerable regex before it can hang the test runner.
        original = re.compile

        def compile_safe(pattern, *args, **kwargs):
            self.assertNotEqual(pattern, r"<!--(.*?)-->")
            return original(pattern, *args, **kwargs)

        with patch("re.compile", side_effect=compile_safe):
            parser = FileParserService()
        text = "<!--a" * 100000
        started = time.monotonic()
        state = parser._init_security_state()
        self.assertEqual(parser._scan_security_line(text, "line 1", state), text)
        self.assertLess(time.monotonic() - started, 2)
        self.assertEqual(state["html_comment_count"], 0)
        _, report = parser._build_security_report("a<!--first--><!--second-->z<!--unclosed")
        self.assertIn("detected: 2", report)

    def test_s4_single_oversized_line_is_split_without_data_loss(self):
        with tempfile.TemporaryDirectory(dir=".") as directory:
            root = Path(directory)
            parser = FileParserService(storage_path=directory)
            parser.INDEX_CHUNK_CHAR_LIMIT = 64
            text = "a" * 1001
            path = root / "input.txt"
            path.write_text(text, encoding="utf-8")
            manifest, truncated = parser._chunk_text_file(str(path), str(root / "chunks"), parser._init_security_state())
            self.assertFalse(truncated)
            self.assertGreater(len(manifest), 1)
            self.assertTrue(all(item["char_count"] <= 64 for item in manifest))
            self.assertEqual("".join(Path(item["chunk_path"]).read_text(encoding="utf-8") for item in manifest), text)
            self.assertTrue(all(item["source"] == {"line_start": 1, "line_end": 1} for item in manifest))
            parser.MAX_INDEX_CHUNKS = 2
            manifest, truncated = parser._chunk_text_file(str(path), str(root / "limited"), parser._init_security_state())
            self.assertEqual(len(manifest), 2)
            self.assertTrue(truncated)


class SecretRedactionTests(unittest.IsolatedAsyncioTestCase):
    secret = "configured-secret-123"
    diagnostic = (
        "configured-secret-123 Authorization: Basic basic-secret\n"
        "Bearer bearer-secret https://alice:password@router.org/path?key=query-secret#fragment-secret"
    )

    def assert_redacted(self, text):
        for secret in (self.secret, "basic-secret", "bearer-secret", "alice", "password", "query-secret", "fragment-secret"):
            self.assertNotIn(secret, text)

    def test_s5_quoted_authorization_and_configured_key_encodings(self):
        self.assertNotIn("digest-secret", redact_diagnostic('Authorization: Digest username="digest-secret", nonce="secret"'))
        self.assertNotIn("basic-secret", redact_diagnostic('{"Authorization": "Basic basic-secret"}'))
        self.assertEqual(redact_diagnostic("provider echoed a%2Fb%2Bc", ("a/b+c",)), "provider echoed [REDACTED]")

    async def test_s5_genai_http_error_is_redacted_including_traceback(self):
        client = GenAIClient(base_url="https://router.org", api_key=self.secret, logger=MagicMock())
        response = httpx.Response(503, text=self.diagnostic)
        with patch("httpx.AsyncClient") as http_client:
            http_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=response)
            try:
                await client.generate(model_id="m", system_instruction="", generation_config={}, messages=[])
                self.fail("Expected LLMError")
            except LLMError as error:
                self.assert_redacted("".join(traceback.format_exception(error)))
                self.assertIsNone(error.raw)
                self.assertIn("503", str(error))

    async def test_s5_genai_sdk_errors_and_model_listing_are_redacted(self):
        client = GenAIClient(base_url="", api_key=self.secret, logger=MagicMock())
        for operation in ("generate", "list"):
            with self.subTest(operation=operation):
                with patch.object(client._client.models, "generate_content", side_effect=RuntimeError(self.diagnostic)), \
                        patch.object(client._client.models, "list", side_effect=RuntimeError(self.diagnostic)):
                    try:
                        if operation == "generate":
                            await client.generate(model_id="m", system_instruction="", generation_config={}, messages=[])
                        else:
                            await client.list_models()
                        self.fail("Expected LLMError")
                    except LLMError as error:
                        self.assert_redacted("".join(traceback.format_exception(error)))

    async def test_s5_gateway_redacts_logs_and_raised_provider_errors(self):
        resolver = SimpleNamespace(
            resolve_role=AsyncMock(return_value=SlotModel("genai", "m", "final")),
            get_endpoint=AsyncMock(return_value={"base_url": "https://router.org", "api_key": self.secret}),
        )
        client = SimpleNamespace(generate=AsyncMock(side_effect=RuntimeError(self.diagnostic)))
        log = MagicMock()
        gateway = LLMGateway(resolver=resolver, logger=log, config=SimpleNamespace(), client_factory=lambda *args: client)
        with self.assertRaises(LLMError) as caught:
            await gateway.generate(role="final", system_instruction="", generation_config={}, messages=[])
        self.assert_redacted(str(caught.exception))
        self.assert_redacted(str(log.warning.call_args_list))
        gateway.log_exception(stage="test", error=RuntimeError(self.diagnostic), user_id="1", role="final", attempt=1, max_attempts=1)
        self.assert_redacted(str(log.error.call_args_list))

    async def test_s5_endpoint_config_log_has_no_url_credentials_or_raw_traceback(self):
        flow = EndpointConfigFlow(
            gateway=SimpleNamespace(list_models_for=AsyncMock(side_effect=RuntimeError(self.diagnostic))),
            resolver=None, db_repo=None,
            config=SimpleNamespace(DONATE_ENCRYPTION_KEY="", ALLOW_PLAINTEXT_ENDPOINT_KEYS=True), admin_user_id="1",
        )
        interaction = SimpleNamespace(response=SimpleNamespace(defer=AsyncMock()), followup=SimpleNamespace(send=AsyncMock()))
        with patch("src.handlers.discord.ui.validate_endpoint_url", return_value=(True, "")), \
                self.assertLogs("src.handlers.discord.ui", level=logging.ERROR) as logs:
            await flow.configure(interaction, "genai", "https://alice:password@router.org/?key=query-secret", self.secret)
        self.assert_redacted("\n".join(logs.output))
        self.assertNotIn("Traceback", "\n".join(logs.output))

    async def test_s5_endpoint_save_failure_redacts_keys_and_traceback(self):
        flow = EndpointConfigFlow(
            gateway=SimpleNamespace(list_models_for=AsyncMock(return_value=[{"id": "m"}])),
            resolver=None,
            db_repo=SimpleNamespace(save_endpoint_config=AsyncMock(
                side_effect=RuntimeError(self.diagnostic + "\nencrypted-secret")
            )),
            config=SimpleNamespace(DONATE_ENCRYPTION_KEY="", ALLOW_PLAINTEXT_ENDPOINT_KEYS=True), admin_user_id="1",
        )
        flow.run_slot_pickers = AsyncMock(return_value={"final": "m"})
        interaction = SimpleNamespace(response=SimpleNamespace(defer=AsyncMock()), followup=SimpleNamespace(send=AsyncMock()))
        with patch("src.handlers.discord.ui.validate_endpoint_url", return_value=(True, "")), \
                patch("src.handlers.discord.ui.encrypt_api_key", return_value="encrypted-secret"), \
                self.assertLogs("src.handlers.discord.ui", level=logging.ERROR) as logs:
            await flow.configure(interaction, "genai", "https://router.org/", self.secret)
        text = "\n".join(logs.output)
        self.assert_redacted(text)
        self.assertNotIn("encrypted-secret", text)
        self.assertNotIn("Traceback", text)


if __name__ == "__main__":
    unittest.main()
