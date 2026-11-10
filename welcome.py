"""Bienvenida del Modo Piloto Automático: guía rápida en pantalla + explicación hablada.

Única fuente de los gestos y de las frases de ejemplo: de acá salen la guía
que dibuja el plugin y la indicación para que Hermes lo explique por voz, así
un gesto nuevo aparece en las dos sin copiar textos. El comportamiento de cada
gesto vive en el overlay (overlay/renderer/shell.js).

Se muestra la primera vez que se entra al modo y con /hermis tour. La parte
hablada se dice una sola vez: ``tour_pending`` se apaga al terminar el turno.
"""
from __future__ import annotations

from typing import Any

from . import ws_server

WELCOME_ID = "hermis-welcome"

GESTURES: tuple[tuple[str, str, str], ...] = (
    ("✊", "Puño (sostenido)", "Cierra la superficie de adelante"),
    ("👋", "Deslizar ← / →", "Pasa a la superficie anterior o siguiente"),
    ("✋", "Palma (sostenida)", "Oculta o muestra todas las superficies"),
)

PHRASES: tuple[tuple[str, str], ...] = (
    ("Muéstrame…", "Datos, una tabla, un gráfico o un documento flotando en pantalla"),
    ("Abre X y ponlo al lado de Y", "Abre apps y acomoda tus ventanas"),
    ("Cierra eso / Cierra todo", "Cierra lo que está en pantalla"),
    ("Sal del piloto automático", "Vuelve al Hermes de siempre"),
)


def guide_data(gestures_on: bool) -> dict[str, Any]:
    """Datos de la superficie ``cards`` con la guía rápida."""
    items: list[dict[str, str]] = [
        {"badge": "Di", "title": phrase, "body": what} for phrase, what in PHRASES
    ]
    items += [{"badge": emoji, "title": name, "body": what} for emoji, name, what in GESTURES]
    if not gestures_on:
        items.append({
            "badge": "📷",
            "title": "Gestos apagados",
            "body": "Actívalos con /hermis gestures on. La cámara funciona solo en el modo piloto "
                    "y las imágenes nunca salen de tu PC.",
        })
    return {"title": "Guía rápida del Modo Piloto", "items": items}


def voice_instruction(gestures_on: bool) -> str:
    """Indicación para que Hermes presente el modo por voz (una sola vez)."""
    gestures = "; ".join(f"{name.lower()}: {what.lower()}" for _, name, what in GESTURES)
    if gestures_on:
        about = f"Los gestos con cámara están activos; nombra cada uno con su función en una sola frase ({gestures})."
    else:
        about = "Menciona que puede activar gestos con cámara con /hermis gestures on."
    return ("Es la PRIMERA VEZ que el usuario usa el Modo Piloto Automático: además de responder, preséntate en "
            "2 o 3 frases habladas y explica cómo se usa: puede pedirte que le muestres cosas en pantalla, que abras "
            f"y acomodes apps, que cierres lo que hay y que salgas del modo. {about} En pantalla tiene una guía "
            "rápida; no la leas entera.")


def entry(gestures_on: bool) -> dict[str, Any]:
    return {"id": WELCOME_ID, "surface": "cards", "data": guide_data(gestures_on)}


def post_llm_call(**kwargs: Any) -> None:
    """Al terminar el turno en que Hermes ya tuvo la indicación, la bienvenida queda cerrada."""
    try:
        st = ws_server.load_state()
        if st.get("tour_pending"):
            st["tour_pending"] = False
            ws_server.save_state(st)
    except Exception:
        return  # nunca frenar ni transformar el turno del agente
