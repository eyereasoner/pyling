"""Example-specific N-Queens builtins for ``../eyeling/examples/queens.n3``."""
from __future__ import annotations

import multiprocessing
import os
from concurrent.futures import ProcessPoolExecutor

from pyling import ListTerm, Literal, XSD_NS

NS = "http://example.org/queens#"
RESULT_CACHE: dict[tuple[int, int], dict[str, object]] = {}


def integer_value(term) -> int | None:
    if not isinstance(term, Literal):
        return None
    try:
        value = int(term.lexical)
    except ValueError:
        return None
    return value if str(value) == term.lexical or term.lexical.startswith("+") else value


def _count_from(args: tuple[int, int, int, int]) -> int:
    all_columns, columns, diag_left, diag_right = args
    if columns == all_columns:
        return 1
    total = 0
    available = all_columns & ~(columns | diag_left | diag_right)
    while available:
        position = available & -available
        available ^= position
        total += _count_from((all_columns, columns | position, (diag_left | position) << 1, (diag_right | position) >> 1))
    return total


def _count_branch(args: tuple[int, int, int, int, int]) -> int:
    all_columns, position, left, right, multiplier = args
    return multiplier * _count_from((all_columns, position, left, right))


def solve_n_queens(n: int, max_print: int) -> dict[str, object]:
    if n <= 0 or n > 31:
        raise RangeError("queens:count expects 1 <= N <= 31")
    if max_print < 0:
        raise RangeError("queens:count expects MAX_PRINT >= 0")

    all_columns = (1 << n) - 1

    def count_from(columns: int, diag_left: int, diag_right: int) -> int:
        if columns == all_columns:
            return 1
        total = 0
        available = all_columns & ~(columns | diag_left | diag_right)
        while available:
            position = available & -available
            available ^= position
            total += count_from(columns | position, (diag_left | position) << 1, (diag_right | position) >> 1)
        return total

    def count_solutions() -> int:
        half = n // 2
        branches: list[tuple[int, int, int, int, int]] = []
        for col in range(half):
            position = 1 << col
            branches.append((all_columns, position, position << 1, position >> 1, 2))
        if n % 2:
            position = 1 << half
            branches.append((all_columns, position, position << 1, position >> 1, 1))
        if n < 13 or "fork" not in multiprocessing.get_all_start_methods():
            return sum(multiplier * count_from(position, left, right) for _, position, left, right, multiplier in branches)
        workers = min(len(branches), os.cpu_count() or 1)
        if workers <= 1:
            return sum(multiplier * count_from(position, left, right) for _, position, left, right, multiplier in branches)
        with ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context("fork")) as executor:
            return sum(executor.map(_count_branch, branches))

    board = [-1] * n
    printed: list[str] = []

    def board_text() -> str:
        lines: list[str] = []
        for row in range(n):
            cells = ["Q" if col == board[row] else "." for col in range(n)]
            lines.append(" ".join(cells))
        lines.append(f"As column positions by row: [{', '.join(str(col + 1) for col in board)}]")
        return "\n".join(lines)

    def collect_printed(row: int, columns: int, diag_left: int, diag_right: int) -> None:
        if len(printed) >= max_print:
            return
        if row == n:
            printed.append(f"Solution {len(printed) + 1}:\n{board_text()}")
            return

        available = all_columns & ~(columns | diag_left | diag_right)
        while available:
            position = available & -available
            available ^= position
            board[row] = position.bit_length() - 1
            collect_printed(row + 1, columns | position, (diag_left | position) << 1, (diag_right | position) >> 1)
            board[row] = -1
            if len(printed) >= max_print:
                return

    count = count_solutions()
    if max_print:
        collect_printed(0, 0, 0, 0)
    return {"count": count, "printed": printed}


class RangeError(ValueError):
    pass


def result_for(n: int, max_print: int) -> dict[str, object]:
    key = (n, max_print)
    result = RESULT_CACHE.get(key)
    if result is None:
        result = solve_n_queens(n, max_print)
        RESULT_CACHE[key] = result
    return result


def subject_parts(ctx) -> tuple[int, int] | None:
    subject = ctx.engine.apply_subst(ctx.goal.s, ctx.subst)
    if not isinstance(subject, ListTerm) or len(subject.elems) != 2:
        return None
    n = integer_value(ctx.engine.apply_subst(subject.elems[0], ctx.subst))
    max_print = integer_value(ctx.engine.apply_subst(subject.elems[1], ctx.subst))
    if n is None or max_print is None:
        return None
    return n, max_print


def count_handler(ctx):
    parts = subject_parts(ctx)
    if parts is None:
        return []
    n, max_print = parts
    count = int(result_for(n, max_print)["count"])
    nxt = ctx.unify_term(ctx.goal.o, Literal(str(count), XSD_NS + "integer", bare=True), ctx.subst)
    return [] if nxt is None else [nxt]


def render_handler(ctx):
    parts = subject_parts(ctx)
    if parts is None:
        return []
    n, max_print = parts
    result = result_for(n, max_print)
    printed: list[str] = result["printed"]  # type: ignore[assignment]
    count = int(result["count"])
    body = "\n".join(
        [
            f"Solving {n}-Queens...",
            f"Printing at most {max_print} solution(s).",
            "",
            *printed,
            *([""] if printed else []),
            f"Total solutions for {n}-Queens: {count}",
            "",
        ]
    )
    nxt = ctx.unify_term(ctx.goal.o, Literal(body, XSD_NS + "string"), ctx.subst)
    return [] if nxt is None else [nxt]


def register(api) -> None:
    api["registerBuiltin"](NS + "count", count_handler)
    api["registerBuiltin"](NS + "render", render_handler)
