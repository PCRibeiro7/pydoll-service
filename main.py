import ipaddress
import os
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Security
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, HttpUrl
from pydoll.browser.chromium import Chrome
from pydoll.browser.options import ChromiumOptions
from pydoll.constants import PageLoadState

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
    options.headless = True
    options.page_load_state = load_state
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-background-networking")
    options.add_argument("--window-size=1920,1080")
    options.block_notifications = True
    options.block_popups = True
    return options


app = FastAPI(title="Pydoll HTTP Service", version="1.0.0")


# ── Request / Response Models ────────────────────────────────────────────────


class ScrapeRequest(BaseModel):
    url: HttpUrl
    selector: str | None = None
    timeout: int = 30


class ScrapeResponse(BaseModel):
    url: str
    title: str
    content: str


class ScreenshotRequest(BaseModel):
    url: HttpUrl
    full_page: bool = False
    quality: int = 90
    timeout: int = 30


class ScreenshotResponse(BaseModel):
    url: str
    image_base64: str


class PdfRequest(BaseModel):
    url: HttpUrl
    landscape: bool = False
    print_background: bool = True
    scale: float = 1.0
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

    async with Chrome(options=create_browser_options()) as browser:
        tab = await browser.start()
        await tab.go_to(validated_url)

        title = await tab.execute_script("return document.title")

        if request.selector:
            element = await tab.query(request.selector)
            content = await element.text
        else:
            content = await tab.execute_script(
                "return document.documentElement.outerHTML"
            )

        return ScrapeResponse(url=validated_url, title=title, content=content)


@app.post("/screenshot", response_model=ScreenshotResponse)
async def screenshot(request: ScreenshotRequest, _=Security(verify_api_key)):
    validated_url = validate_url(str(request.url))

    async with Chrome(
        options=create_browser_options(PageLoadState.COMPLETE)
    ) as browser:
        tab = await browser.start()
        await tab.go_to(validated_url)

        image_base64 = await tab.take_screenshot(
            as_base64=True,
            quality=request.quality,
            beyond_viewport=request.full_page,
        )

        return ScreenshotResponse(url=validated_url, image_base64=image_base64)


@app.post("/pdf", response_model=PdfResponse)
async def pdf(request: PdfRequest, _=Security(verify_api_key)):
    validated_url = validate_url(str(request.url))

    async with Chrome(
        options=create_browser_options(PageLoadState.COMPLETE)
    ) as browser:
        tab = await browser.start()
        await tab.go_to(validated_url)

        pdf_base64 = await tab.print_to_pdf(
            as_base64=True,
            landscape=request.landscape,
            print_background=request.print_background,
            scale=request.scale,
        )

        return PdfResponse(url=validated_url, pdf_base64=pdf_base64)
