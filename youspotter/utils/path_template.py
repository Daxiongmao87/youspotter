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



def to_path_regex(tmpl: str) -> str:
    r"""Convert a user template into a regex over a POSIX-style relative path.

    Example: "{artist}/{album}/{artist} - {title}.{ext}" ->
      r"^(?P<artist>.+?)/(?P<album>.+?)/(?P<artist>.+?)\s-\s(?P<title>.+?)\.(?P<ext>[^/]+)$"

    We keep the groups non-greedy to avoid over-capturing across separators.
    """
    validate_user_template(tmpl)
    # Temporarily replace placeholders with tokens, then escape, then re-insert groups
    tok_map = {var: f"__VAR_{var.upper()}__" for var in ALLOWED_VARS}
    tmp = tmpl
    for var, tok in tok_map.items():
        tmp = tmp.replace("{" + var + "}", tok)
    import re as _re
    esc = _re.escape(tmp)
    # Replace tokens with named groups
    esc = esc.replace(tok_map['artist'], r"(?P<artist>.+?)")
    esc = esc.replace(tok_map['album'], r"(?P<album>.+?)")
    esc = esc.replace(tok_map['title'], r"(?P<title>.+?)")
    esc = esc.replace(tok_map['ext'], r"(?P<ext>[^/]+)")
    # Anchor to full relative path
    return r"^" + esc + r"$"
