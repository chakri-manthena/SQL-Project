from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from sqlglot import Dialect


COMPARISONS = {"EQ", "NEQ", "LT", "LTE", "GT", "GTE"}
KEYWORD_CANDIDATES = (
    "SELECT",
    "FROM",
    "WHERE",
    "GROUP",
    "ORDER",
    "HAVING",
    "DISTINCT",
    "BETWEEN",
    "LIMIT",
    "JOIN",
    "DESC",
)
IDENTIFIER_TYPES = {"VAR", "IDENTIFIER"}
TOKENIZER = Dialect.get_or_raise("mysql").tokenizer()


@dataclass(frozen=True)
class TokenEdit:
    start: int
    end: int
    replacement: str
    rule: str


def _edit_distance(left: str, right: str) -> int:
    previous = list(range(len(right) + 1))
    for left_index, left_char in enumerate(left, start=1):
        current = [left_index]
        for right_index, right_char in enumerate(right, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[right_index] + 1,
                    previous[right_index - 1] + (left_char != right_char),
                )
            )
        previous = current
    return previous[-1]


def _token_name(token) -> str:
    return str(token.text).strip("`\"'").upper()


def _is_identifier(token) -> bool:
    return token.token_type.name in IDENTIFIER_TYPES


def _replace_tokens(sql: str, edits: list[TokenEdit]) -> str:
    for edit in sorted(edits, key=lambda item: (item.start, item.end), reverse=True):
        sql = sql[: edit.start] + edit.replacement + sql[edit.end + 1 :]
    return sql


def _tokens(sql: str):
    return TOKENIZER.tokenize(sql)


def _where_bounds(tokens) -> tuple[int, int] | None:
    start = next((index + 1 for index, token in enumerate(tokens) if token.token_type.name == "WHERE"), None)
    if start is None:
        return None
    end = len(tokens)
    for index in range(start, len(tokens)):
        if tokens[index].token_type.name in {"GROUP_BY", "ORDER_BY", "HAVING", "LIMIT", "SEMICOLON"}:
            end = index
            break
    return start, end


def _known(values: Iterable[str]) -> set[str]:
    return {str(value).strip("`\"'").lower() for value in values}


def _r1(sql: str) -> tuple[str, bool]:
    edits = [
        TokenEdit(token.start, token.end, "=", "R1")
        for token in _tokens(sql)
        if token.token_type.name == "EQ" and token.text == "=="
    ]
    return _replace_tokens(sql, edits), bool(edits)


def _r2(sql: str) -> tuple[str, bool]:
    replacements = {"DAMP": "AND", "DPIPE": "OR"}
    edits = [
        TokenEdit(token.start, token.end, replacements[token.token_type.name], "R2")
        for token in _tokens(sql)
        if token.token_type.name in replacements
    ]
    return _replace_tokens(sql, edits), bool(edits)


def _r3(sql: str) -> tuple[str, bool]:
    tokens = _tokens(sql)
    edits = []
    for index in range(len(tokens) - 1):
        if tokens[index].token_type.name not in {"EQ", "NEQ"}:
            continue
        if tokens[index + 1].token_type.name != "NULL":
            continue
        operator = "IS" if tokens[index].token_type.name == "EQ" else "IS NOT"
        edits.append(TokenEdit(tokens[index].start, tokens[index].end, operator, "R3"))
    return _replace_tokens(sql, edits), bool(edits)


def _r4(sql: str) -> tuple[str, bool]:
    tokens = _tokens(sql)
    edits = []
    removable_before = {"FROM", "WHERE", "GROUP_BY", "ORDER_BY"}
    for index, token in enumerate(tokens):
        if token.token_type.name != "COMMA":
            continue
        next_type = tokens[index + 1].token_type.name if index + 1 < len(tokens) else None
        if next_type in removable_before | {"SEMICOLON", None}:
            edits.append(TokenEdit(token.start, token.end, "", "R4"))
    return _replace_tokens(sql, edits), bool(edits)


def _r5(sql: str, known_identifiers: set[str]) -> tuple[str, bool]:
    edits = []
    for token in _tokens(sql):
        if token.token_type.name != "VAR":
            continue
        value = _token_name(token)
        if len(value) < 4 or value.lower() in known_identifiers:
            continue
        distances = [(keyword, _edit_distance(value, keyword)) for keyword in KEYWORD_CANDIDATES]
        nearest = min(distance for _, distance in distances)
        matches = [keyword for keyword, distance in distances if distance == nearest]
        if nearest <= 2 and len(matches) == 1:
            edits.append(TokenEdit(token.start, token.end, matches[0], "R5"))
    return _replace_tokens(sql, edits), bool(edits)


def _r6(
    sql: str,
    known_columns: set[str],
    known_tables: set[str],
    aliases: set[str],
) -> tuple[str, bool]:
    tokens = _tokens(sql)
    bounds = _where_bounds(tokens)
    if bounds is None:
        return sql, False
    start, end = bounds
    known = known_columns | known_tables | aliases
    edits = []
    for index in range(start + 1, end - 1):
        operator = tokens[index]
        if operator.token_type.name not in COMPARISONS:
            continue
        left_start = index - 3 if index >= 3 and tokens[index - 2].token_type.name == "DOT" else index - 1
        right_end = index + 3 if index + 2 < end and tokens[index + 2].token_type.name == "DOT" else index + 1
        if left_start < start or right_end >= end:
            continue
        left_component, right_component = tokens[left_start], tokens[right_end]
        left_qualified = left_start != index - 1
        right_qualified = right_end != index + 1
        if not (_is_identifier(left_component) and _is_identifier(right_component)):
            continue
        left_name = _token_name(left_component).lower()
        right_name = _token_name(right_component).lower()
        if left_name in known_columns and right_name not in known and not right_qualified:
            edits.append(TokenEdit(right_component.start, right_component.end, "'" + right_component.text.replace("'", "''") + "'", "R6"))
        elif right_name in known_columns and left_name not in known and not left_qualified:
            edits.append(TokenEdit(left_component.start, left_component.end, "'" + left_component.text.replace("'", "''") + "'", "R6"))
    return _replace_tokens(sql, edits), bool(edits)


def repair_query(
    query: str | None,
    known_columns: Iterable[str] = (),
    known_tables: Iterable[str] = (),
    aliases: Iterable[str] = (),
) -> dict:
    if not isinstance(query, str) or not query.strip():
        return {"query": None, "rules": [], "reason": "empty query"}

    columns = _known(known_columns)
    tables = _known(known_tables)
    alias_names = _known(aliases)
    known_identifiers = columns | tables | alias_names
    result = query
    applied = []
    for rule_name, rule in (
        ("R1", _r1),
        ("R2", _r2),
        ("R3", _r3),
        ("R4", _r4),
        ("R5", lambda value: _r5(value, known_identifiers)),
        ("R6", lambda value: _r6(value, columns, tables, alias_names)),
    ):
        result, changed = rule(result)
        if changed:
            applied.append(rule_name)
    if not applied:
        return {"query": None, "rules": [], "reason": "no rule matched"}
    return {"query": result, "rules": applied, "reason": None}