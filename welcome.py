"""Bienvenida del Modo Piloto Automático: guía rápida en pantalla + explicación hablada.

Única fuente de los gestos y de las frases de ejemplo: de acá salen la guía
que dibuja el plugin y la indicación para que Hermes lo explique por voz, así
un gesto nuevo aparece en las dos sin copiar textos. El comportamiento de cada
gesto vive en el overlay (overlay/renderer/shell.js).

Los textos salen del catálogo (messages/*.json) para que la guía exista en el
idioma de la interfaz, no solo en español.

Se muestra la primera vez que se entra al modo y con /hermis tour. La parte
hablada se dice una sola vez: ``tour_pending`` se apaga al terminar el turno.
"""
from __future__ import annotations

from typing import Any

from . import i18n, ws_server

WELCOME_ID = "hermis-welcome"

# (emoji, clave del nombre, clave de la descripción) en el catálogo.
GESTURES: tuple[tuple[str, str, str], ...] = (
    ("✊", "welcome.gesture.fist.name", "welcome.gesture.fist.what"),
    ("👋", "welcome.gesture.swipe.name", "welcome.gesture.swipe.what"),
    ("✋", "welcome.gesture.palm.name", "welcome.gesture.palm.what"),
)

# (clave del ejemplo, clave de la explicación) en el catálogo.
PHRASES: tuple[tuple[str, str], ...] = (
    ("welcome.phrase.show.title", "welcome.phrase.show.what"),
    ("welcome.phrase.layout.title", "welcome.phrase.layout.what"),
    ("welcome.phrase.close.title", "welcome.phrase.close.what"),
    ("welcome.phrase.exit.title", "welcome.phrase.exit.what"),
)


def guide_data(gestures_on: bool, locale: str | None = None) -> dict[str, Any]:
    """Datos de la superficie ``cards`` con la guía rápida."""
    loc = locale or i18n.get_locale()
    items: list[dict[str, str]] = [
        {"badge": i18n.t("welcome.badge_say", loc), "title": i18n.t(title, loc), "body": i18n.t(what, loc)}
        for title, what in PHRASES
    ]
    items += [
        {"badge": emoji, "title": i18n.t(name, loc), "body": i18n.t(what, loc)}
        for emoji, name, what in GESTURES
    ]
    if not gestures_on:
        items.append({
            "badge": i18n.t("welcome.gestures_off_badge", loc),
            "title": i18n.t("welcome.gestures_off_title", loc),
            "body": i18n.t("welcome.gestures_off_body", loc),
        })
    return {"title": i18n.t("welcome.guide_title", loc), "items": items}


def voice_instruction(gestures_on: bool, locale: str | None = None) -> str:
    """Indicación para que Hermes presente el modo por voz (una sola vez)."""
    loc = locale or i18n.get_locale()
    gestures = "; ".join(
        f"{i18n.t(name, loc).lower()}: {i18n.t(what, loc).lower()}" for _, name, what in GESTURES
    )
    if gestures_on:
        about = i18n.t("welcome.voice.gestures_on", loc, gestures=gestures)
    else:
        about = i18n.t("welcome.voice.gestures_off", loc)
    return i18n.t("welcome.voice.intro", loc, about=about)


def entry(gestures_on: bool, locale: str | None = None) -> dict[str, Any]:
    return {"id": WELCOME_ID, "surface": "cards", "data": guide_data(gestures_on, locale)}


def post_llm_call(**kwargs: Any) -> None:
    """Al terminar el turno en que Hermes ya tuvo la indicación, la bienvenida queda cerrada."""
    try:
        st = ws_server.load_state()
        if st.get("tour_pending"):
            st["tour_pending"] = False
            ws_server.save_state(st)
    except Exception:
        return  # nunca frenar ni transformar el turno del agente
