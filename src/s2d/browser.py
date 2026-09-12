import time
from contextlib import contextmanager
from pathlib import Path

from playwright.sync_api import BrowserContext, sync_playwright
from playwright.sync_api import Error as PlaywrightError

LOGIN_URL = "https://account.deezer.com/en/login?redirect_uri=https%3A%2F%2Fwww.deezer.com%2Fen%2F"


class ProfileInUse(Exception):
    pass


# Deezer's bot check fires on Playwright's default automation flags, so they are
# stripped and the system Chrome is preferred over the bundled Chromium.
LAUNCH_ARGS = dict(
    ignore_default_args=["--enable-automation"],
    args=["--disable-blink-features=AutomationControlled"],
)


@contextmanager
def persistent_context(profile: Path, headless: bool, channel: str | None):
    profile.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        try:
            ctx = p.chromium.launch_persistent_context(str(profile), headless=headless, channel=channel, **LAUNCH_ARGS)
        except PlaywrightError as e:
            if "ProcessSingleton" in str(e):
                raise ProfileInUse(profile) from None
            if channel is None or "not found" not in str(e):
                raise
            ctx = p.chromium.launch_persistent_context(str(profile), headless=headless, **LAUNCH_ARGS)
        try:
            yield ctx
        finally:
            try:
                ctx.close()
            except Exception:
                pass


def is_logged_in(ctx: BrowserContext) -> bool:
    return any(c["name"] == "arl" and c["domain"].endswith("deezer.com") for c in ctx.cookies())


def has_session(profile: Path, channel: str | None) -> bool:
    with persistent_context(profile, headless=True, channel=channel) as ctx:
        return is_logged_in(ctx)


def login(profile: Path, channel: str | None) -> bool:
    with persistent_context(profile, headless=False, channel=channel) as ctx:
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(LOGIN_URL)
        print("Log in to Deezer in the browser window, then close the window.")
        ctx.wait_for_event("close", timeout=0)
    return has_session(profile, channel)


def wait_security_check(page, timeout_s: int = 120) -> None:
    for _ in range(timeout_s):
        if "Security check" not in page.content():
            return
        time.sleep(1)
    raise RuntimeError("Deezer security check did not clear")
