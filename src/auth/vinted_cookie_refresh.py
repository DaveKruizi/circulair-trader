"""
Vinted cookie refresher via Playwright.

Logt automatisch in op vinted.nl met email/wachtwoord en extraheert
de access_token_web cookie. Draait als stap in GitHub Actions vóór de scraper.

Gebruik:
    python src/auth/vinted_cookie_refresh.py

Omgevingsvariabelen (verplicht):
    VINTED_EMAIL      - Vinted account e-mailadres
    VINTED_PASSWORD   - Vinted account wachtwoord

Output:
    stdout  - de ruwe cookie-waarde (en niets anders), zodat de workflow hem kan opvangen
    stderr  - diagnostische logging
    exit 0  - cookie gevonden
    exit 1  - mislukt (workflow valt terug op opgeslagen secret)
"""

import os
import sys
import time


# ---------------------------------------------------------------------------
# Stealth helpers
# ---------------------------------------------------------------------------

def _apply_stealth(page) -> None:
    """Verberg webdriver-indicators zo goed mogelijk."""
    try:
        from playwright_stealth import stealth_sync
        stealth_sync(page)
        _log("Stealth mode actief")
    except ImportError:
        _log("playwright-stealth niet geïnstalleerd — zonder stealth (minder betrouwbaar)")
        # Handmatige minimale stealth via init script
        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3] });
        """)


def _log(msg: str) -> None:
    print(f"[cookie_refresh] {msg}", file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# Cookie consent afhandeling
# ---------------------------------------------------------------------------

_CONSENT_SELECTORS = [
    "button[data-testid='accept-all-button']",
    "button[id='onetrust-accept-btn-handler']",
    "button:has-text('Accepteer alle')",
    "button:has-text('Alles accepteren')",
    "button:has-text('Accepteer')",
    "[class*='cookie'] button:has-text('Accept')",
]

def _dismiss_consent(page) -> None:
    for sel in _CONSENT_SELECTORS:
        try:
            btn = page.locator(sel).first
            if btn.is_visible(timeout=1500):
                btn.click()
                _log(f"Cookie-banner gesloten ({sel})")
                time.sleep(0.8)
                return
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Login formulier invullen
# ---------------------------------------------------------------------------

_EMAIL_SELECTORS = [
    "input[name='email']",
    "input[type='email']",
    "input[data-testid='login-email-input']",
    "input[data-testid='email-input']",
    "#email",
    "input[autocomplete='email']",
]

_PASSWORD_SELECTORS = [
    "input[name='password']",
    "input[type='password']",
    "input[data-testid='login-password-input']",
    "input[data-testid='password-input']",
    "#password",
    "input[autocomplete='current-password']",
]

_SUBMIT_SELECTORS = [
    "button[type='submit']",
    "button[data-testid='login-submit']",
    "button[data-testid='submit-button']",
    "button:has-text('Inloggen')",
    "button:has-text('Log in')",
    "button:has-text('Aanmelden')",
    "input[type='submit']",
]


def _fill_first_visible(page, selectors: list[str], value: str, label: str) -> bool:
    for sel in selectors:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=2000):
                el.click()
                el.fill(value)
                _log(f"{label} ingevuld via '{sel}'")
                return True
        except Exception:
            pass
    _log(f"WAARSCHUWING: geen zichtbaar veld gevonden voor {label}")
    return False


def _click_first_visible(page, selectors: list[str], label: str) -> bool:
    for sel in selectors:
        try:
            btn = page.locator(sel).first
            if btn.is_visible(timeout=2000):
                btn.click()
                _log(f"{label} geklikt via '{sel}'")
                return True
        except Exception:
            pass
    _log(f"WAARSCHUWING: geen zichtbare knop gevonden voor {label}")
    return False


# ---------------------------------------------------------------------------
# Hoofdfunctie
# ---------------------------------------------------------------------------

def refresh_vinted_cookie() -> str | None:
    email = os.getenv("VINTED_EMAIL", "").strip()
    password = os.getenv("VINTED_PASSWORD", "").strip()

    if not email or not password:
        _log("VINTED_EMAIL en/of VINTED_PASSWORD niet ingesteld als omgevingsvariabele.")
        _log("Voeg deze toe als GitHub Actions secrets om automatisch in te loggen.")
        return None

    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
    except ImportError:
        _log("FOUT: playwright niet geïnstalleerd. Voer 'pip install playwright' uit.")
        return None

    _log(f"Start Playwright login voor {email[:3]}***")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
                "--disable-extensions",
            ],
        )
        context = browser.new_context(
            viewport={"width": 1366, "height": 768},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            locale="nl-NL",
            timezone_id="Europe/Amsterdam",
        )
        page = context.new_page()
        _apply_stealth(page)

        try:
            # ----------------------------------------------------------------
            # Stap 1: Laad startpagina (cookie-consent afhandelen)
            # ----------------------------------------------------------------
            _log("Laden van vinted.nl...")
            page.goto("https://www.vinted.nl", wait_until="domcontentloaded", timeout=30_000)
            time.sleep(1.5)
            _dismiss_consent(page)

            # ----------------------------------------------------------------
            # Stap 2: Navigeer naar loginpagina
            # ----------------------------------------------------------------
            _log("Navigeren naar loginpagina...")
            page.goto("https://www.vinted.nl/auth/login", wait_until="domcontentloaded", timeout=30_000)
            time.sleep(2)
            _dismiss_consent(page)

            _log(f"Huidige URL: {page.url}")

            # ----------------------------------------------------------------
            # Stap 3: Vul formulier in
            # ----------------------------------------------------------------
            _fill_first_visible(page, _EMAIL_SELECTORS, email, "E-mail")
            time.sleep(0.5)
            _fill_first_visible(page, _PASSWORD_SELECTORS, password, "Wachtwoord")
            time.sleep(0.5)

            # Kleine pauze — lijkt menselijker
            page.keyboard.press("Tab")
            time.sleep(0.3)

            _click_first_visible(page, _SUBMIT_SELECTORS, "Login-knop")

            # ----------------------------------------------------------------
            # Stap 4: Wacht op succesvolle login
            # ----------------------------------------------------------------
            _log("Wachten op redirect na login...")
            try:
                page.wait_for_url(
                    lambda url: "auth/login" not in url and "auth" not in url.split("?")[0],
                    timeout=20_000,
                )
                _log(f"Redirect naar: {page.url}")
            except PlaywrightTimeout:
                _log(f"Geen redirect — huidige URL: {page.url}")
                # Toch doorgaan en kijken of cookie al aanwezig is

            time.sleep(2)

            # ----------------------------------------------------------------
            # Stap 5: Extraheer de cookie
            # ----------------------------------------------------------------
            cookies = context.cookies()
            cookie_names = [c["name"] for c in cookies]
            _log(f"Aanwezige cookies: {cookie_names}")

            for c in cookies:
                if c["name"] == "access_token_web":
                    _log(f"Cookie gevonden! Lengte: {len(c['value'])} tekens")
                    return c["value"]

            # Geen cookie → log de paginatitel als hint
            title = page.title()
            _log(f"Cookie NIET gevonden. Paginatitel: '{title}'")
            _log("Mogelijke oorzaken: verkeerde inloggegevens, 2FA, of IP-blokkade door Vinted.")
            return None

        except Exception as exc:
            _log(f"Onverwachte fout: {exc}")
            try:
                _log(f"URL op moment van fout: {page.url}")
            except Exception:
                pass
            return None

        finally:
            browser.close()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    cookie = refresh_vinted_cookie()
    if cookie:
        print(cookie)   # Alleen de ruwe waarde naar stdout — workflow vangt dit op
        sys.exit(0)
    else:
        _log("Login mislukt — workflow zal terugvallen op opgeslagen secret.")
        sys.exit(1)
