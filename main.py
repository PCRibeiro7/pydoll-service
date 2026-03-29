import asyncio
import ipaddress
import logging
import os
import sys
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Security
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, HttpUrl
from pydoll.browser.chromium import Chrome
from pydoll.browser.options import ChromiumOptions
from pydoll.constants import PageLoadState
from pydoll.exceptions import CommandExecutionTimeout

logger = logging.getLogger(__name__)

MAX_RETRIES = 3

API_KEY = os.environ.get("API_KEY", "")

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def verify_api_key(api_key: str = Security(api_key_header)):
    if not API_KEY:
        return
    if api_key != API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API key")


def validate_url(url: str) -> str:
    """Reject private/internal URLs to prevent SSRF."""
    parsed = urlparse(url)
    hostname = parsed.hostname
    if not hostname:
        raise HTTPException(status_code=400, detail="Invalid URL")

    blocked = {
        "localhost",
        "127.0.0.1",
        "0.0.0.0",
        "::1",
        "metadata.google.internal",
        "169.254.169.254",
    }
    if hostname in blocked:
        raise HTTPException(status_code=400, detail="Internal URLs are not allowed")

    try:
        ip = ipaddress.ip_address(hostname)
        if ip.is_private or ip.is_loopback or ip.is_link_local:
            raise HTTPException(
                status_code=400, detail="Private IP addresses are not allowed"
            )
    except ValueError:
        pass

    return url


def create_browser_options(
    load_state: PageLoadState = PageLoadState.INTERACTIVE,
) -> ChromiumOptions:
    options = ChromiumOptions()
    options.page_load_state = load_state
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-background-networking")
    options.add_argument("--disable-default-apps")
    options.add_argument("--disable-sync")
    options.add_argument("--disable-translate")
    options.add_argument("--single-process")
    options.add_argument("--js-flags=--max-old-space-size=512")
    # Non-headless Chrome is required to bypass Cloudflare Turnstile.
    # On Windows (local dev) we move the window offscreen;
    # on Linux (Docker) Xvfb provides a virtual display.
    if sys.platform == "win32":
        options.add_argument("--window-position=-2400,-2400")
    options.webrtc_leak_protection = True
    options.block_notifications = True
    options.block_popups = True
    return options


app = FastAPI(title="Pydoll HTTP Service", version="1.0.0")


def _extract_value(cdp_response: dict):
    """Extract the actual value from a CDP Runtime.evaluate response."""
    return cdp_response["result"]["result"]["value"]


async def _navigate(tab, url: str, bypass_cloudflare: bool, wait: int, timeout: int):
    """Navigate to a URL, optionally bypassing Cloudflare, and wait for content."""
    if bypass_cloudflare:
        try:
            async with tab.expect_and_bypass_cloudflare_captcha(
                time_to_wait_captcha=timeout,
            ):
                await tab.go_to(url)
        except (CommandExecutionTimeout, TimeoutError):
            # The setup/cleanup phase can time out on resource-constrained
            # hosts. If the page already loaded, it is safe to continue;
            # otherwise the caller's retry loop will handle it.
            pass
        # After the bypass clicks the checkbox, Cloudflare still needs time to
        # verify and redirect. Poll until the page title is no longer the
        # challenge page ("Just a moment...").
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            try:
                title = _extract_value(
                    await tab.execute_script("return document.title")
                )
            except (CommandExecutionTimeout, TimeoutError):
                await asyncio.sleep(0.5)
                continue
            if title and "just a moment" not in title.lower():
                break
            await asyncio.sleep(0.5)
    else:
        await tab.go_to(url)

    if wait > 0:
        await asyncio.sleep(wait)


# ── Request / Response Models ────────────────────────────────────────────────


class ScrapeRequest(BaseModel):
    url: HttpUrl
    selector: str | None = None
    bypass_cloudflare: bool = True
    wait: int = 0
    timeout: int = 30


class ScrapeResponse(BaseModel):
    url: str
    title: str
    content: str


class ScreenshotRequest(BaseModel):
    url: HttpUrl
    full_page: bool = False
    quality: int = 90
    bypass_cloudflare: bool = True
    wait: int = 0
    timeout: int = 30


class ScreenshotResponse(BaseModel):
    url: str
    image_base64: str


class PdfRequest(BaseModel):
    url: HttpUrl
    landscape: bool = False
    print_background: bool = True
    scale: float = 1.0
    bypass_cloudflare: bool = True
    wait: int = 0
    timeout: int = 30


class PdfResponse(BaseModel):
    url: str
    pdf_base64: str


# ── Endpoints ────────────────────────────────────────────────────────────────


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/scrape", response_model=ScrapeResponse)
async def scrape(request: ScrapeRequest, _=Security(verify_api_key)):
    validated_url = validate_url(str(request.url))

    last_exc: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            async with Chrome(options=create_browser_options()) as browser:
                tab = await browser.start()
                await _navigate(
                    tab, validated_url,
                    request.bypass_cloudflare, request.wait, request.timeout,
                )

                title = _extract_value(
                    await tab.execute_script("return document.title")
                )

                if request.selector:
                    element = await tab.query(request.selector)
                    content = await element.text
                else:
                    content = _extract_value(
                        await tab.execute_script(
                            "return document.documentElement.outerHTML"
                        )
                    )

                return ScrapeResponse(url=validated_url, title=title, content=content)
        except (TimeoutError, CommandExecutionTimeout) as exc:
            last_exc = exc
            logger.warning("Attempt %d/%d failed: %s", attempt, MAX_RETRIES, exc)
            await asyncio.sleep(attempt)  # linear back-off

    raise HTTPException(status_code=504, detail=f"Browser timed out after {MAX_RETRIES} attempts: {last_exc}")


@app.post("/screenshot", response_model=ScreenshotResponse)
async def screenshot(request: ScreenshotRequest, _=Security(verify_api_key)):
    validated_url = validate_url(str(request.url))

    last_exc: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            async with Chrome(options=create_browser_options()) as browser:
                tab = await browser.start()
                await _navigate(
                    tab, validated_url,
                    request.bypass_cloudflare, request.wait, request.timeout,
                )

                image_base64 = await tab.take_screenshot(
                    as_base64=True,
                    quality=request.quality,
                    beyond_viewport=request.full_page,
                )

                return ScreenshotResponse(url=validated_url, image_base64=image_base64)
        except (TimeoutError, CommandExecutionTimeout) as exc:
            last_exc = exc
            logger.warning("Attempt %d/%d failed: %s", attempt, MAX_RETRIES, exc)
            await asyncio.sleep(attempt)

    raise HTTPException(status_code=504, detail=f"Browser timed out after {MAX_RETRIES} attempts: {last_exc}")


@app.post("/pdf", response_model=PdfResponse)
async def pdf(request: PdfRequest, _=Security(verify_api_key)):
    validated_url = validate_url(str(request.url))

    last_exc: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            async with Chrome(options=create_browser_options()) as browser:
                tab = await browser.start()
                await _navigate(
                    tab, validated_url,
                    request.bypass_cloudflare, request.wait, request.timeout,
                )

                pdf_base64 = await tab.print_to_pdf(
                    as_base64=True,
                    landscape=request.landscape,
                    print_background=request.print_background,
                    scale=request.scale,
                )

                return PdfResponse(url=validated_url, pdf_base64=pdf_base64)
        except (TimeoutError, CommandExecutionTimeout) as exc:
            last_exc = exc
            logger.warning("Attempt %d/%d failed: %s", attempt, MAX_RETRIES, exc)
            await asyncio.sleep(attempt)

    raise HTTPException(status_code=504, detail=f"Browser timed out after {MAX_RETRIES} attempts: {last_exc}")
