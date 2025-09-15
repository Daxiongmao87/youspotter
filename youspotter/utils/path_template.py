import re

ALLOWED_VARS = {"artist", "album", "title", "ext"}


def validate_user_template(tmpl: str) -> None:
    if tmpl.startswith("/"):
        raise ValueError("template must be relative, not start with '/'")
    if ".." in tmpl:
        raise ValueError("template must not contain '..'")
    vars_found = set(re.findall(r"\{([a-zA-Z0-9_]+)\}", tmpl))
    illegal = vars_found - ALLOWED_VARS
    if illegal:
        raise ValueError(f"illegal variables in template: {', '.join(sorted(illegal))}")
    if "ext" not in vars_found:
        raise ValueError("template must include {ext}")


def to_ytdlp_outtmpl(tmpl: str) -> str:
    validate_user_template(tmpl)
    out = tmpl
    for var in ALLOWED_VARS:
        out = out.replace("{" + var + "}", f"%({var})s")
    return out

