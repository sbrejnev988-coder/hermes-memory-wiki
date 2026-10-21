"""Ограниченный stdlib-only evaluator для извлечения XLSX, не движок Excel.

Публичный контракт и сознательные ограничения: docs/SPREADSHEET_FORMULAS_RU.md.
Входные formula strings — данные для собственного lexer/parser, не Python-код.
Модуль не открывает файлы, не импортирует плагины и не исполняет external links.
"""
from __future__ import annotations

from collections.abc import Mapping
import math
import re

__all__ = ["evaluate_cells"]

# Независимые жёсткие ceilings не позволяют отключить ограниченность аргументом.
_LIMITS = {"max_cells": 100000, "max_range_cells": 100000,
           "max_operations": 250000, "max_depth": 64}
_MAX_FORMULA = 8192
_MAX_TOKENS = 4096
_MAX_TEXT = 32767
_MAX_SHEETS = 10000
_MAX_ARGUMENTS = 255
_MAX_ROW = 1048576
_MAX_COLUMN = 16384
_COORD = re.compile(r"([A-Z]{1,3})([1-9][0-9]{0,6})\Z", re.ASCII)
_REF = re.compile(r"\$?([A-Z]{1,3})\$?([1-9][0-9]{0,6})\Z", re.ASCII)
_NUMBER = re.compile(r"(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[Ee][+-]?[0-9]+)?", re.ASCII)
_SIGNED_NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[Ee][+-]?[0-9]+)?\Z", re.ASCII)
_ERRORS = ("#GETTING_DATA", "#DIV/0!", "#VALUE!", "#SPILL!", "#CALC!",
           "#NAME?", "#NULL!", "#REF!", "#NUM!", "#N/A")
_AGGREGATES = frozenset(("SUM", "AVERAGE", "MIN", "MAX", "COUNT", "COUNTA", "PRODUCT"))
_FUNCTIONS = _AGGREGATES | {"ABS"}


class _Refusal(Exception):
    """Только bounded internal codes, никогда текст исходной формулы."""

    def __init__(self, status, reason):
        self.status = status
        self.reason = reason
        super().__init__(reason)


class _Scalar:
    __slots__ = ("kind", "value", "reference")

    def __init__(self, kind, value=None, reference=False):
        self.kind = kind
        self.value = value
        self.reference = reference


def _error(code):
    return _Scalar("error", code)


def _number(value):
    # Не вызывать __float__ / arithmetic произвольного foreign object.
    try:
        number = float(value)
    except (OverflowError, ValueError):
        return _error("#NUM!")
    return _Scalar("number", number) if math.isfinite(number) else _error("#NUM!")


def _coordinates(token, *, reference=False):
    match = (_REF if reference else _COORD).fullmatch(token)
    if match is None:
        return None
    column = 0
    for char in match[1]:
        column = column * 26 + ord(char) - ord("A") + 1
    row = int(match[2])
    if column > _MAX_COLUMN or row > _MAX_ROW:
        return None
    return column, row


def _cell_id(column, row):
    letters = ""
    while column:
        column, remainder = divmod(column - 1, 26)
        letters = chr(ord("A") + remainder) + letters
    return letters + str(row)


def _literal(value, ctype):
    """OOXML typed values, включая нынешние rendered numeric/bool strings."""
    if type(value) not in (str, int, float, bool, type(None)):
        raise ValueError("cell_value_must_be_plain_scalar")
    if type(value) is str and len(value) > _MAX_TEXT:
        raise _Refusal("resource_limit", "text_length_limit")
    if ctype not in ("", "n", "b", "s", "str", "inlineStr", "e"):
        raise _Refusal("unsupported", "cell_type_unsupported")
    if ctype == "e":
        return _error(value if type(value) is str and value in _ERRORS else "#VALUE!")
    if ctype in ("s", "str", "inlineStr"):
        if value is None:
            return _Scalar("blank")
        if type(value) is not str:
            return _error("#VALUE!")
        return _Scalar("text", value)
    if value is None or (type(value) is str and value == ""):
        return _Scalar("blank")
    if ctype == "b":
        if type(value) is bool:
            return _Scalar("boolean", value)
        if type(value) is int and value in (0, 1):
            return _Scalar("boolean", bool(value))
        if type(value) is str and value in ("0", "1", "TRUE", "FALSE"):
            return _Scalar("boolean", value in ("1", "TRUE"))
        return _error("#VALUE!")
    if type(value) is bool:
        return _Scalar("boolean", value) if ctype == "" else _error("#VALUE!")
    if type(value) in (int, float):
        return _number(value)
    stripped = value.strip(" \t\r\n")
    if _SIGNED_NUMBER.fullmatch(stripped):
        return _number(stripped)
    return _Scalar("text", value) if ctype == "" else _error("#VALUE!")


def _numeric(value):
    if value.kind == "error":
        return value
    if value.kind == "blank":
        return _Scalar("number", 0.0)
    if value.kind == "boolean":
        return _Scalar("number", float(value.value))
    if value.kind == "number":
        return value
    text = value.value.strip(" \t\r\n")
    return _number(text) if _SIGNED_NUMBER.fullmatch(text) else _error("#VALUE!")


class _Budget:
    __slots__ = ("remaining", "depth", "range_cells")

    def __init__(self, operations, depth, range_cells):
        self.remaining = operations
        self.depth = depth
        self.range_cells = range_cells

    def spend(self):
        if self.remaining == 0:
            raise _Refusal("resource_limit", "operation_limit")
        self.remaining -= 1

    def check_depth(self, depth):
        if depth > self.depth:
            raise _Refusal("resource_limit", "depth_limit")


class _Parser:
    """Bounded lexer + precedence parser; AST состоит только из tuple/scalars."""

    def __init__(self, formula, budget):
        if len(formula) > _MAX_FORMULA:
            raise _Refusal("resource_limit", "formula_length_limit")
        self.budget = budget
        self.tokens = []
        self.position = 0
        self._lex(formula[1:] if formula.startswith("=") else formula)

    def _emit(self, kind, value):
        self.budget.spend()
        if len(self.tokens) >= _MAX_TOKENS:
            raise _Refusal("resource_limit", "token_limit")
        self.tokens.append((kind, value))

    def _lex(self, text):
        i = 0
        while i < len(text):
            char = text[i]
            if char in " \t\r\n":
                i += 1
                continue
            if char in ('"', "'"):
                quote = char
                i += 1
                chars = []
                while i < len(text):
                    if text[i] == quote:
                        if i + 1 < len(text) and text[i + 1] == quote:
                            chars.append(quote)
                            i += 2
                            continue
                        i += 1
                        break
                    chars.append(text[i])
                    i += 1
                else:
                    raise _Refusal("unsupported", "invalid_formula")
                value = "".join(chars)
                if quote == "'" and any(c in value for c in "[]:/\\|"):
                    raise _Refusal("external_refused", "external_or_3d_reference_refused")
                self._emit("text" if quote == '"' else "sheet", value)
            elif char in "[]\\|":
                raise _Refusal("external_refused", "external_reference_refused")
            elif char == "#":
                match = next((e for e in _ERRORS if text.startswith(e, i)), None)
                if match is None:
                    raise _Refusal("unsupported", "error_or_spill_syntax_unsupported")
                self._emit("error", match)
                i += len(match)
            elif char in "0123456789" or (char == "." and i + 1 < len(text)
                                          and text[i + 1] in "0123456789"):
                match = _NUMBER.match(text, i)
                if match is None:
                    raise _Refusal("unsupported", "invalid_formula")
                self._emit("number", match[0])
                i = match.end()
            elif char == "$" or char.isalpha() or char == "_":
                start = i
                i += 1
                while i < len(text) and (text[i].isalnum() or text[i] in "_.$"):
                    i += 1
                self._emit("word", text[start:i])
            elif char in "+-*/^%(),:!":
                self._emit(char, char)
                i += 1
            else:
                raise _Refusal("unsupported", "operator_or_syntax_unsupported")
        self.tokens.append(("end", ""))

    def _peek(self, kind):
        return self.tokens[self.position][0] == kind

    def _take(self, kind=None):
        token = self.tokens[self.position]
        # EOF остаётся sentinel: незавершённый operand/reference не должен
        # сдвинуть lookahead за tokens даже при _take() без expected kind.
        if token[0] == "end" or kind is not None and token[0] != kind:
            raise _Refusal("unsupported", "invalid_formula")
        self.position += 1
        return token

    def parse(self):
        node = self._expr(0, 0)
        if not self._peek("end"):
            raise _Refusal("unsupported", "syntax_or_intersection_unsupported")
        return node

    def _expr(self, minimum, depth):
        self.budget.check_depth(depth)
        if self._peek("+") or self._peek("-"):
            operator = self._take()[0]
            left = ("unary", operator, self._expr(40, depth + 1))
        else:
            left = self._primary(depth)
        while True:
            if self._peek("%") and minimum <= 50:
                self._take()
                left = ("unary", "%", left)
                continue
            operator = self.tokens[self.position][0]
            precedence = {"+": 10, "-": 10, "*": 20, "/": 20, "^": 30}.get(operator, -1)
            if precedence < minimum:
                break
            self._take()
            # Excel negation binds before power; repeated ^ associates left.
            right = self._expr(precedence + 1, depth + 1)
            left = ("binary", operator, left, right)
        return left

    def _reference(self, token):
        sheet = None
        if token[0] == "sheet" or self._peek("!"):
            sheet = token[1]
            self._take("!")
            token = self._take("word")
        if token[0] != "word":
            raise _Refusal("unsupported", "invalid_reference")
        coordinates = _coordinates(token[1], reference=True)
        if coordinates is None:
            raise _Refusal("unsupported", "name_or_reference_unsupported")
        return ("reference", sheet, *coordinates)

    def _primary(self, depth):
        token = self._take()
        kind, value = token
        if kind in ("number", "text", "error"):
            return (kind, value)
        if kind == "(":
            node = self._expr(0, depth + 1)
            self._take(")")
            return node
        if kind not in ("word", "sheet"):
            raise _Refusal("unsupported", "invalid_formula")
        if kind == "word" and self._peek("("):
            function = value.upper()
            if function not in _FUNCTIONS:
                raise _Refusal("unsupported", "function_unsupported")
            self._take()
            args = []
            if not self._peek(")"):
                while True:
                    if len(args) >= _MAX_ARGUMENTS:
                        raise _Refusal("resource_limit", "argument_limit")
                    args.append(self._expr(0, depth + 1))
                    if not self._peek(","):
                        break
                    self._take()
            self._take(")")
            if function == "ABS" and len(args) != 1:
                raise _Refusal("unsupported", "function_arity_unsupported")
            return ("function", function, tuple(args))
        if kind == "word" and not self._peek("!") and value.upper() in ("TRUE", "FALSE"):
            return ("boolean", value.upper() == "TRUE")
        left = self._reference(token)
        if self._peek(":"):
            self._take()
            right = self._reference(self._take())
            if right[1] is not None and right[1] != left[1]:
                raise _Refusal("unsupported", "cross_sheet_range_unsupported")
            return ("range", left[1], left[2], left[3], right[2], right[3])
        return left


class _Evaluator:
    def __init__(self, workbook, budget):
        self.workbook = workbook
        self.budget = budget
        self.memo = {}
        self.active = set()
        self.parsed = {}

    def cell(self, sheet, coordinate, depth=0):
        self.budget.spend()
        self.budget.check_depth(depth)
        key = sheet, coordinate
        if key in self.memo:
            result = self.memo[key]
            if type(result) is tuple:
                # Не сохранять и не переиспользовать exception/traceback: общий
                # refused dependency иначе накапливает frames на каждом caller.
                raise _Refusal(*result)
            return result
        if sheet not in self.workbook:
            return _error("#REF!")
        record = self.workbook[sheet].get(coordinate)
        if record is None:
            return _Scalar("blank")
        if not record["formula"]:
            result = _literal(record["value"], record["type"])
            self.memo[key] = result
            return result
        if key in self.active:
            raise _Refusal("cycle", "cyclic_dependency")
        self.active.add(key)
        try:
            if key not in self.parsed:
                self.parsed[key] = _Parser(record["formula"], self.budget).parse()
            result = self.node(self.parsed[key], sheet, depth + 1)
            if result.kind == "blank":
                result = _Scalar("number", 0.0)
            # Публичный результат не переносит reference-coercion flag дальше.
            result = _Scalar(result.kind, result.value)
            self.memo[key] = result
            return result
        except _Refusal as refusal:
            # Depth — контекст traversal, а не свойство самой dependency cell.
            # Не отравлять memo суффикса, доступного позже от короткого root.
            if refusal.reason != "depth_limit":
                self.memo[key] = (refusal.status, refusal.reason)
            raise
        finally:
            self.active.remove(key)

    def _reference(self, sheet, column, row, depth):
        result = self.cell(sheet, _cell_id(column, row), depth)
        return _Scalar(result.kind, result.value, reference=True)

    def node(self, node, sheet, depth):
        self.budget.spend()
        self.budget.check_depth(depth)
        kind = node[0]
        if kind == "number":
            return _number(node[1])
        if kind in ("text", "boolean", "error"):
            return _Scalar(kind, node[1])
        if kind == "reference":
            return self._reference(sheet if node[1] is None else node[1], node[2], node[3], depth + 1)
        if kind == "range":
            raise _Refusal("unsupported", "range_requires_aggregate")
        if kind == "unary":
            value = _numeric(self.node(node[2], sheet, depth + 1))
            if value.kind == "error":
                return value
            return _number(-value.value if node[1] == "-" else value.value / 100 if node[1] == "%" else value.value)
        if kind == "binary":
            left = _numeric(self.node(node[2], sheet, depth + 1))
            right = _numeric(self.node(node[3], sheet, depth + 1))
            if left.kind == "error":
                return left
            if right.kind == "error":
                return right
            a, b = left.value, right.value
            try:
                if node[1] == "+":
                    answer = a + b
                elif node[1] == "-":
                    answer = a - b
                elif node[1] == "*":
                    answer = a * b
                elif node[1] == "/":
                    if b == 0:
                        return _error("#DIV/0!")
                    answer = a / b
                else:
                    # math.pow: bounded double arithmetic, без giant Python int
                    # и без complex values для fractional negative-base powers.
                    if a == 0 and b < 0:
                        return _error("#DIV/0!")
                    if a == 0 and b == 0:
                        return _error("#NUM!")
                    answer = math.pow(a, b)
                return _number(answer)
            except (OverflowError, ValueError):
                return _error("#NUM!")
        if node[1] == "ABS":
            value = _numeric(self.node(node[2][0], sheet, depth + 1))
            return value if value.kind == "error" else _number(abs(value.value))
        return self._aggregate(node[1], node[2], sheet, depth)

    def _values(self, arg, sheet, depth):
        if arg[0] != "range":
            yield self.node(arg, sheet, depth + 1)
            return
        self.budget.spend()
        self.budget.check_depth(depth + 1)
        target = sheet if arg[1] is None else arg[1]
        c1, c2 = min(arg[2], arg[4]), max(arg[2], arg[4])
        r1, r2 = min(arg[3], arg[5]), max(arg[3], arg[5])
        size = (c2 - c1 + 1) * (r2 - r1 + 1)
        if size > self.budget.range_cells:
            raise _Refusal("resource_limit", "range_cell_limit")
        if target not in self.workbook:
            yield _error("#REF!")
            return
        for row in range(r1, r2 + 1):
            for column in range(c1, c2 + 1):
                yield self._reference(target, column, row, depth + 2)

    def _aggregate(self, function, args, sheet, depth):
        total, count, product = 0.0, 0, 1.0
        low, high = None, None
        for arg in args:
            for value in self._values(arg, sheet, depth):
                self.budget.spend()
                if function == "COUNTA":
                    count += value.kind != "blank"
                    continue
                if value.kind == "error":
                    # COUNT считает только числа: Excel error values не
                    # считаются, как в references, так и в direct expressions.
                    # Это не относится к _Refusal: unsupported/cycle/resource
                    # поднимается из _values раньше и не превращается в0.
                    if function == "COUNT":
                        continue
                    return value
                if value.kind == "blank" or value.reference and value.kind in ("text", "boolean"):
                    continue
                value = _numeric(value)
                if value.kind == "error":
                    # COUNT игнорирует прямой nonnumeric text, остальные numeric
                    # aggregates отказывают #VALUE!, а не дают правдоподобный0.
                    if function == "COUNT":
                        continue
                    return value
                count += 1
                if function == "COUNT":
                    continue
                number = value.value
                if function in ("SUM", "AVERAGE"):
                    total += number
                    if not math.isfinite(total):
                        return _error("#NUM!")
                elif function == "PRODUCT":
                    product *= number
                    if not math.isfinite(product):
                        return _error("#NUM!")
                elif function == "MIN":
                    low = number if low is None else min(low, number)
                else:
                    high = number if high is None else max(high, number)
        if function in ("COUNT", "COUNTA"):
            return _number(count)
        if function == "AVERAGE":
            return _number(total / count) if count else _error("#DIV/0!")
        if function == "MIN":
            return _number(low if low is not None else 0)
        if function == "MAX":
            return _number(high if high is not None else 0)
        if function == "PRODUCT":
            return _number(product if count else 0)
        return _number(total)


def _validate(workbook, max_cells):
    if not isinstance(workbook, Mapping):
        raise ValueError("workbook_must_be_mapping")
    if len(workbook) > _MAX_SHEETS:
        raise ValueError("sheet_count_limit")
    total = 0
    for sheet, cells in workbook.items():
        if type(sheet) is not str or not sheet or len(sheet) > 1024:
            raise ValueError("sheet_id_must_be_bounded_nonempty_string")
        if not isinstance(cells, Mapping):
            raise ValueError("sheet_cells_must_be_mapping")
        total += len(cells)
        if total > max_cells:
            raise ValueError("max_cells_exceeded")
        for coordinate, record in cells.items():
            if type(coordinate) is not str or _coordinates(coordinate) is None:
                raise ValueError("invalid_literal_cell_id")
            if type(record) is not dict or not {"value", "formula", "type"}.issubset(record):
                raise ValueError("cell_must_be_plain_record")
            if type(record["formula"]) is not str or type(record["type"]) is not str:
                raise ValueError("formula_and_type_must_be_strings")
            if len(record["type"]) > 64:
                raise ValueError("cell_type_length_limit")
            if type(record["value"]) not in (str, int, float, bool, type(None)):
                raise ValueError("cell_value_must_be_plain_scalar")


def _result(record, scalar=None, refusal=None):
    formula = record["formula"]
    result = {"value": None, "value_type": "unknown", "formula": formula, "type": record["type"],
              "status": "literal", "value_origin": "input", "reason": "", "error": None,
              "cached_value": None, "cached_value_type": "unknown", "cache_status": "not_applicable"}
    if formula:
        try:
            cached = _literal(record["value"], record["type"])
            result["cached_value_type"] = cached.kind
            result["cache_status"] = "absent" if cached.kind == "blank" else "available"
            result["cached_value"] = cached.value
        except _Refusal:
            result["cache_status"] = "invalid"
        if result["cached_value_type"] == "error" and not (
                record["type"] == "e" and type(record["value"]) is str and record["value"] in _ERRORS):
            # _literal синтезирует #VALUE! для повреждённого typed input. Это
            # диагностическая ошибка, а не существовавший в workbook cache.
            result.update(cache_status="invalid", cached_value=None, cached_value_type="unknown")
    if refusal is not None:
        result.update(status=refusal.status, value_origin="none", reason=refusal.reason)
    else:
        result.update(value_type=scalar.kind, value=scalar.value,
                      status="computed" if formula else "literal",
                      value_origin="evaluated" if formula else "input")
        if scalar.kind == "error":
            result.update(status="error", value=None, error=scalar.value,
                          reason="formula_error" if formula else "input_error")
    return result


def evaluate_cells(workbook, *, max_cells=100000, max_range_cells=100000,
                   max_operations=250000, max_depth=64):
    """Вернуть новый exact-key workbook с typed значениями и честным provenance.

    Неверная форма/IDs/параметры и превышение max_cells: атомарный ValueError.
    Formula/dependency отказ: status unsupported/external_refused/cycle/
    resource_limit, value=None, value_origin=none. Excel errors отдельны.
    Cached value сохраняется только как metadata и никогда не служит fallback.
    Порядок входных mappings определяет расход общего operation budget.
    """
    for name, value in (("max_cells", max_cells), ("max_range_cells", max_range_cells),
                        ("max_operations", max_operations), ("max_depth", max_depth)):
        if type(value) is not int or not 1 <= value <= _LIMITS[name]:
            raise ValueError("invalid_" + name)
    _validate(workbook, max_cells)
    evaluator = _Evaluator(workbook, _Budget(max_operations, max_depth, max_range_cells))
    output = {}
    for sheet, cells in workbook.items():
        output[sheet] = {}
        for coordinate, record in cells.items():
            try:
                # Literals не теряются при исчерпании formula operation budget.
                scalar = (evaluator.cell(sheet, coordinate) if record["formula"]
                          else _literal(record["value"], record["type"]))
                output[sheet][coordinate] = _result(record, scalar=scalar)
            except _Refusal as refusal:
                output[sheet][coordinate] = _result(record, refusal=refusal)
    return output
