"""Tiny translation table for the words drawn on the built-in cards."""

from __future__ import annotations

LANGUAGES = ("en", "es")

_TEXT: dict[str, dict[str, str]] = {
    "en": {
        "cpu": "CPU",
        "memory": "MEMORY",
        "network": "NETWORK",
        "temperature": "TEMPERATURE",
        "storage": "STORAGE",
        "uptime": "UPTIME",
        "no_data": "NO DATA",
        "no_data_card": "No data yet",
        "free": "free",
        "used": "used",
        "of": "of",
        "total": "total",
        "peak": "peak",
        "in": "in",
        "out": "out",
        "now": "now",
        "load": "load",
        "up": "up",
        "since": "since",
        "available": "available",
        "swap": "swap",
        "arc": "ZFS ARC",
        "collecting": "Collecting history...",
        "no_history": "No history yet",
        "no_images": "No images found",
        "card_failed": "Card failed",
        "cores": "cores",
        "temp": "Temperature",
        "avg": "avg",
        "missing": "missing",
        "time_units": "d h m",
        "weekdays": "Monday Tuesday Wednesday Thursday Friday Saturday Sunday",
        "months": "January February March April May June July August September October "
        "November December",
    },
    "es": {
        "cpu": "CPU",
        "memory": "MEMORIA",
        "network": "RED",
        "temperature": "TEMPERATURA",
        "storage": "ALMACENAMIENTO",
        "uptime": "TIEMPO ENCENDIDO",
        "no_data": "SIN DATOS",
        "no_data_card": "Todavía sin datos",
        "free": "libre",
        "used": "usado",
        "of": "de",
        "total": "en total",
        "peak": "pico",
        "in": "entra",
        "out": "sale",
        "now": "ahora",
        "load": "carga",
        "up": "encendido",
        "since": "desde",
        "available": "disponible",
        "swap": "swap",
        "arc": "ARC ZFS",
        "collecting": "Reuniendo historial...",
        "no_history": "Sin historial todavía",
        "no_images": "No hay imágenes",
        "card_failed": "Falló la tarjeta",
        "cores": "núcleos",
        "temp": "Temperatura",
        "avg": "media",
        "missing": "no encontrado",
        "time_units": "d h min",
        "weekdays": "lunes martes miércoles jueves viernes sábado domingo",
        "months": "enero febrero marzo abril mayo junio julio agosto septiembre octubre "
        "noviembre diciembre",
    },
}


def tr(key: str, lang: str = "en") -> str:
    """Translated text for ``key``; falls back to English, then to the key itself."""
    return _TEXT.get(lang, _TEXT["en"]).get(key) or _TEXT["en"].get(key, key)


def time_units(lang: str = "en") -> tuple[str, str, str]:
    d, h, m = tr("time_units", lang).split()
    return d, h, m


def localized_strftime(moment, fmt: str, lang: str = "en") -> str:
    """strftime that translates %A/%a/%B/%b without touching the process locale."""
    weekdays = tr("weekdays", lang).split()
    months = tr("months", lang).split()
    day_name = weekdays[moment.weekday()]
    month_name = months[moment.month - 1]
    replacements = {
        "%A": day_name.capitalize() if lang == "en" else day_name,
        "%a": day_name[:3].capitalize() if lang == "en" else day_name[:3],
        "%B": month_name.capitalize() if lang == "en" else month_name,
        "%b": month_name[:3].capitalize() if lang == "en" else month_name[:3],
    }
    out = []
    i = 0
    while i < len(fmt):
        pair = fmt[i : i + 2]
        if pair in replacements:
            out.append(replacements[pair].replace("%", "%%"))
            i += 2
        elif pair == "%%":
            out.append("%%")
            i += 2
        else:
            out.append(fmt[i])
            i += 1
    return moment.strftime("".join(out))
