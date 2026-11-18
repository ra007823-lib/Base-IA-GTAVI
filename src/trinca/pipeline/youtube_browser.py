"""Envio ao YouTube pelo YouTube Studio, controlando o navegador com o Playwright.

Não usa a API de envio do YouTube. O app abre uma janela do Chrome com um perfil
próprio e persistente (dentro da pasta de dados, só o usuário lê). No primeiro
uso você entra na sua conta Google nessa janela; depois o login é reaproveitado.

Cuidados:
- a senha nunca passa pelo app: o login é feito por você, na janela do navegador;
- só arquivos de vídeo existentes são enviados;
- a interface do Studio muda de vez em quando. Se um passo falhar, o erro diz
  qual foi e o vídeo fica como rascunho no Studio para você terminar à mão.
"""

from __future__ import annotations

import os
import time
from datetime import datetime
from pathlib import Path

from ..config import data_dir
from ..security import is_allowed_url
from .contracts import Cancelled, IsCancelled, PlatformCopy, Progress, ServiceError

UPLOAD_URL = "https://www.youtube.com/upload?hl=en"
VIDEO_SUFFIXES = frozenset({".mp4", ".mov", ".webm", ".mkv"})
LOGIN_TIMEOUT_S = 300
UPLOAD_TIMEOUT_S = 30 * 60
STEP_TIMEOUT_MS = 30_000
TITLE_MAX = 100
DESCRIPTION_MAX = 5000

_INSTALL_HINT = (
    "O Playwright não está instalado. Rode: pip install playwright "
    "(o app usa o Google Chrome já instalado no sistema)."
)

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def profile_dir() -> Path:
    path = data_dir() / "perfil-youtube"
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, 0o700)
    return path


def compose_description(copy: PlatformCopy) -> str:
    text = copy.description.strip()
    if copy.hashtags.strip():
        text += "\n\n" + copy.hashtags.strip()
    return text[:DESCRIPTION_MAX]


def format_schedule(scheduled_at: str) -> tuple[str, str]:
    """('Nov 16, 2026', '2:30 PM') a partir de 'yyyy-MM-ddTHH:mm:ss' (a interface está em inglês)."""
    when = datetime.fromisoformat(scheduled_at)
    hour = when.hour % 12 or 12
    return (
        f"{_MONTHS[when.month - 1]} {when.day}, {when.year}",
        f"{hour}:{when.minute:02d} {'AM' if when.hour < 12 else 'PM'}",
    )


class BrowserYouTube:
    """Publisher que envia e agenda o vídeo no YouTube Studio."""

    def schedule(
        self, copy: PlatformCopy, render_path: str, scheduled_at: str, progress: Progress,
        cancelled: IsCancelled,
    ) -> str:
        video = Path(render_path) if render_path else None
        if (
            video is None or not video.is_absolute() or not video.is_file()
            or video.suffix.lower() not in VIDEO_SUFFIXES
        ):
            raise ServiceError(
                "O vídeo renderizado ainda não existe. A renderização é a etapa 3 do projeto."
            )
        schedule = None
        if scheduled_at:
            try:
                schedule = format_schedule(scheduled_at)
            except ValueError as exc:
                raise ServiceError("O horário de publicação é inválido.") from exc

        try:
            from playwright.sync_api import Error as PlaywrightError
            from playwright.sync_api import TimeoutError as PlaywrightTimeout
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise ServiceError(_INSTALL_HINT) from exc

        step = "abrir o navegador"
        try:
            with sync_playwright() as pw:
                progress(5, "Abrindo o navegador")
                context = self._launch(pw)
                try:
                    page = context.pages[0] if context.pages else context.new_page()
                    page.set_default_timeout(STEP_TIMEOUT_MS)
                    step = "entrar no YouTube Studio"
                    self._open_studio(page, progress, cancelled)
                    step = "enviar o arquivo"
                    return self._upload(page, copy, video, schedule, progress, cancelled)
                finally:
                    context.close()
        except (Cancelled, ServiceError):
            raise
        except PlaywrightTimeout as exc:
            raise ServiceError(
                f"O YouTube Studio demorou demais no passo: {step}. "
                "Confira o rascunho no Studio e tente de novo."
            ) from exc
        except PlaywrightError as exc:
            raise ServiceError(f"Falha ao controlar o navegador no passo: {step}.") from exc

    @staticmethod
    def _launch(pw):  # noqa: ANN001, ANN205
        options = dict(
            user_data_dir=str(profile_dir()), headless=False, locale="en-US",
            ignore_default_args=["--enable-automation"],
            args=["--disable-blink-features=AutomationControlled"],
        )
        try:
            return pw.chromium.launch_persistent_context(channel="chrome", **options)
        except Exception:  # noqa: BLE001 - sem Chrome, tenta o Chromium do Playwright
            try:
                return pw.chromium.launch_persistent_context(**options)
            except Exception as exc:  # noqa: BLE001
                raise ServiceError(
                    "Não consegui abrir o navegador. Instale o Google Chrome ou rode "
                    "'playwright install chromium'."
                ) from exc

    @staticmethod
    def _check(cancelled: IsCancelled) -> None:
        if cancelled():
            raise Cancelled()

    def _wait_until(self, condition, timeout_s: float, cancelled: IsCancelled) -> bool:  # noqa: ANN001
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            self._check(cancelled)
            if condition():
                return True
            time.sleep(1)
        return False

    def _open_studio(self, page, progress: Progress, cancelled: IsCancelled) -> None:  # noqa: ANN001
        progress(10, "Abrindo o YouTube Studio")
        page.goto(UPLOAD_URL)
        if "accounts.google.com" in page.url:
            progress(15, "Entre na sua conta Google na janela que abriu")
            ok = self._wait_until(
                lambda: "accounts.google.com" not in page.url, LOGIN_TIMEOUT_S, cancelled
            )
            if not ok:
                raise ServiceError("O login na conta Google não foi concluído a tempo.")
            page.goto(UPLOAD_URL)

    def _upload(self, page, copy, video, schedule, progress, cancelled) -> str:  # noqa: ANN001
        progress(25, "Enviando o arquivo")
        page.locator('input[type="file"]').first.set_input_files(str(video))
        self._check(cancelled)

        progress(45, "Preenchendo título e descrição")
        title = page.locator("#title-textarea #textbox")
        title.click()
        title.press("Control+A")
        title.fill(copy.title[:TITLE_MAX])
        description = page.locator("#description-textarea #textbox")
        description.click()
        description.fill(compose_description(copy))
        page.locator('[name="VIDEO_MADE_FOR_KIDS_NOT_MFK"]').click()
        url = ""
        link = page.locator(".video-url-fadeable a")
        if link.count():
            url = (link.first.get_attribute("href") or "").strip()
        self._check(cancelled)

        progress(60, "Avançando pelas etapas")
        for _ in range(3):
            page.locator("#next-button").click()
            self._check(cancelled)

        if schedule:
            progress(75, "Agendando a publicação")
            page.locator("#second-container-expand-button").click()
            page.locator("#schedule-radio-button").click()
            page.locator("#datepicker-trigger").click()
            date_input = page.locator("tp-yt-paper-dialog #textbox").last
            date_input.fill(schedule[0])
            date_input.press("Enter")
            time_input = page.locator("#time-of-day-container #textbox")
            time_input.fill(schedule[1])
            time_input.press("Enter")
        else:
            progress(75, "Publicando")
            page.locator('tp-yt-paper-radio-button[name="PUBLIC"]').click()

        progress(85, "Aguardando o envio terminar")
        done = page.locator("#done-button")
        if not self._wait_until(
            lambda: done.get_attribute("aria-disabled") != "true", UPLOAD_TIMEOUT_S, cancelled
        ):
            raise ServiceError("O envio do vídeo não terminou a tempo.")
        done.click()
        page.wait_for_timeout(3000)
        progress(100, "Concluído")
        return url if is_allowed_url(url) else ""
