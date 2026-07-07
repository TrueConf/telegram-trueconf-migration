import i18n
from pathlib import Path


def setup_i18n(lang: str = "ru"):
    i18n.load_path.append(str(Path(__file__).parent / "locales"))
    i18n.set("locale", lang)
    i18n.set("filename_format", "{locale}.{format}")
    i18n.set("fallback", "ru")


_ = i18n.t
