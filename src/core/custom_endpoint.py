from urllib.parse import urlsplit, urlunsplit


CUSTOM_ENDPOINT_PRESETS = {
    "manual": "",
    "lm_studio": "http://127.0.0.1:1234/",
    "ollama": "http://127.0.0.1:11434/",
}


def resolve_custom_endpoint_preset(preset: str) -> str:
    return CUSTOM_ENDPOINT_PRESETS.get(str(preset or "manual").strip().lower(), "")


def normalize_custom_endpoint(endpoint: str) -> str:
    raw = str(endpoint or "").strip()
    if not raw:
        raise ValueError("Endpoint custom API không được để trống.")

    parts = urlsplit(raw)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ValueError("Endpoint phải bắt đầu bằng http:// hoặc https://.")

    segments = [segment for segment in parts.path.split("/") if segment]
    if not segments or segments[-1].lower() != "v1":
        segments.append("v1")

    path = "/" + "/".join(segments)
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def custom_models_url(normalized_base_url: str) -> str:
    return f"{str(normalized_base_url or '').rstrip('/')}/models"
