import re

_CREATE_TABLE_RE = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[`\"\[]?(?P<name>[A-Za-z_][A-Za-z0-9_]*)[`\"\]]?\s*\(",
    re.IGNORECASE,
)
_LINE_COMMENT_RE = re.compile(r"--[^\n]*")
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_COLUMN_NAME_RE = re.compile(r"[`\"\[]?([A-Za-z_][A-Za-z0-9_]*)[`\"\]]?")
_TABLE_CONSTRAINTS = {"PRIMARY", "UNIQUE", "CHECK", "FOREIGN", "CONSTRAINT"}


def strip_sql_comments(script: str) -> str:
    script = _BLOCK_COMMENT_RE.sub(" ", script)
    return _LINE_COMMENT_RE.sub(" ", script)


def _find_matching_paren(text: str, open_index: int) -> int:
    depth = 0
    quote: str | None = None
    i = open_index
    while i < len(text):
        char = text[i]
        if quote is not None:
            if char == quote:
                if i + 1 < len(text) and text[i + 1] == quote:
                    i += 2
                    continue
                quote = None
        elif char in ("'", '"'):
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _split_definitions(body: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    quote: str | None = None
    i = 0
    while i < len(body):
        char = body[i]
        if quote is not None:
            current.append(char)
            if char == quote:
                if i + 1 < len(body) and body[i + 1] == quote:
                    current.append(body[i + 1])
                    i += 2
                    continue
                quote = None
        elif char in ("'", '"'):
            quote = char
            current.append(char)
        elif char == "(":
            depth += 1
            current.append(char)
        elif char == ")":
            depth -= 1
            current.append(char)
        elif char == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
        i += 1
    if current:
        parts.append("".join(current))
    return parts


def parse_create_tables(script: str) -> dict[str, list[tuple[str, str]]]:
    script = strip_sql_comments(script)
    tables: dict[str, list[tuple[str, str]]] = {}

    for match in _CREATE_TABLE_RE.finditer(script):
        open_index = match.end() - 1
        close_index = _find_matching_paren(script, open_index)
        if close_index == -1:
            continue

        table = match.group("name")
        columns: list[tuple[str, str]] = []
        for part in _split_definitions(script[match.end():close_index]):
            part = part.strip()
            if not part:
                continue
            head = part.split(None, 1)[0].upper()
            if head in _TABLE_CONSTRAINTS:
                continue
            column = _COLUMN_NAME_RE.match(part)
            if column:
                columns.append((column.group(1), part))
        tables[table] = columns

    return tables
