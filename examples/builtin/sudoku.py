"""Example-specific Sudoku builtins for ``../eyeling/examples/sudoku.n3``."""
from __future__ import annotations

from pyling import Literal, XSD_NS

NS = "http://example.org/sudoku-builtin#"
ALL = 0x1FF
REPORT_CACHE: dict[str, dict[str, object]] = {}


def string_lit(value: str) -> Literal:
    return Literal(value, XSD_NS + "string")


def bool_lit(value: bool) -> Literal:
    return Literal("true" if value else "false", XSD_NS + "boolean", bare=True)


def int_lit(value: int) -> Literal:
    return Literal(str(value), XSD_NS + "integer", bare=True)


def digit_mask(value: int) -> int:
    return 1 << (value - 1)


def box_index(row: int, col: int) -> int:
    return (row // 3) * 3 + (col // 3)


def digits(mask: int) -> list[int]:
    return [digit for digit in range(1, 10) if mask & digit_mask(digit)]


def format_board(cells: list[int]) -> str:
    rows: list[str] = []
    for row in range(9):
        if row > 0 and row % 3 == 0:
            rows.append("")
        parts: list[str] = []
        for col in range(9):
            if col > 0 and col % 3 == 0:
                parts.append("|")
            value = cells[row * 9 + col]
            parts.append("." if value == 0 else str(value))
        rows.append(" ".join(parts) + " ")
    return "\n".join(rows) + "\n"


def parse_puzzle(raw: str) -> dict[str, object]:
    filtered = [ch for ch in raw if not ch.isspace() and ch not in {"|", "+"}]
    if len(filtered) != 81:
        return {"error": f"Expected exactly 81 cells after removing whitespace, but found {len(filtered)}."}
    cells = [0] * 81
    for index, ch in enumerate(filtered):
        if "1" <= ch <= "9":
            cells[index] = ord(ch) - 48
        elif ch not in {"0", ".", "_"}:
            return {"error": f"Unexpected character '{ch}' at position {index + 1}."}
    return {"cells": cells}


def new_state() -> dict[str, object]:
    return {
        "cells": [0] * 81,
        "row_used": [0] * 9,
        "col_used": [0] * 9,
        "box_used": [0] * 9,
        "moves": [],
    }


def clone_state(state: dict[str, object]) -> dict[str, object]:
    return {
        "cells": list(state["cells"]),  # type: ignore[arg-type]
        "row_used": list(state["row_used"]),  # type: ignore[arg-type]
        "col_used": list(state["col_used"]),  # type: ignore[arg-type]
        "box_used": list(state["box_used"]),  # type: ignore[arg-type]
        "moves": list(state["moves"]),  # type: ignore[arg-type]
    }


def place(state: dict[str, object], index: int, value: int) -> bool:
    cells: list[int] = state["cells"]  # type: ignore[assignment]
    if cells[index] != 0:
        return cells[index] == value
    row = index // 9
    col = index % 9
    box = box_index(row, col)
    bit = digit_mask(value)
    row_used: list[int] = state["row_used"]  # type: ignore[assignment]
    col_used: list[int] = state["col_used"]  # type: ignore[assignment]
    box_used: list[int] = state["box_used"]  # type: ignore[assignment]
    if (row_used[row] | col_used[col] | box_used[box]) & bit:
        return False
    cells[index] = value
    row_used[row] |= bit
    col_used[col] |= bit
    box_used[box] |= bit
    return True


def candidates(state: dict[str, object], index: int) -> int:
    row = index // 9
    col = index % 9
    box = box_index(row, col)
    row_used: list[int] = state["row_used"]  # type: ignore[assignment]
    col_used: list[int] = state["col_used"]  # type: ignore[assignment]
    box_used: list[int] = state["box_used"]  # type: ignore[assignment]
    return ALL & ~(row_used[row] | col_used[col] | box_used[box])


def state_from_puzzle(cells: list[int]) -> dict[str, object]:
    state = new_state()
    for index, value in enumerate(cells):
        if value == 0:
            continue
        if value < 1 or value > 9:
            return {"error": f"Cell {index + 1} contains {value}, but only digits 1-9 or 0/. are allowed."}
        if not place(state, index, value):
            row = index // 9 + 1
            col = index % 9 + 1
            return {"error": f"The given clues already conflict at row {row}, column {col}."}
    return {"state": state}


def propagate_singles(state: dict[str, object], stats: dict[str, int]) -> bool:
    cells: list[int] = state["cells"]  # type: ignore[assignment]
    moves: list[dict[str, object]] = state["moves"]  # type: ignore[assignment]
    while True:
        progress = False
        for index in range(81):
            if cells[index] != 0:
                continue
            mask = candidates(state, index)
            count = mask.bit_count()
            if count == 0:
                return False
            if count == 1:
                digit = digits(mask)[0]
                moves.append({"index": index, "value": digit, "candidates_mask": mask, "forced": True})
                if not place(state, index, digit):
                    return False
                stats["forcedMoves"] += 1
                progress = True
        if not progress:
            return True


def select_unfilled_cell(state: dict[str, object]) -> dict[str, int] | None:
    cells: list[int] = state["cells"]  # type: ignore[assignment]
    best: dict[str, int] | None = None
    for index in range(81):
        if cells[index] != 0:
            continue
        mask = candidates(state, index)
        count = mask.bit_count()
        if best is None or count < best["count"]:
            best = {"index": index, "mask": mask, "count": count}
        if count == 2:
            break
    return best


def solve(state: dict[str, object], stats: dict[str, int], depth: int) -> dict[str, object] | None:
    stats["recursiveNodes"] += 1
    stats["maxDepth"] = max(stats["maxDepth"], depth)
    current = clone_state(state)
    if not propagate_singles(current, stats):
        stats["backtracks"] += 1
        return None
    best = select_unfilled_cell(current)
    if best is None:
        return current
    for digit in digits(best["mask"]):
        next_state = clone_state(current)
        candidates_mask = candidates(next_state, best["index"])
        moves: list[dict[str, object]] = next_state["moves"]  # type: ignore[assignment]
        moves.append({"index": best["index"], "value": digit, "candidates_mask": candidates_mask, "forced": False})
        stats["guessedMoves"] += 1
        if not place(next_state, best["index"], digit):
            continue
        solved = solve(next_state, stats, depth + 1)
        if solved is not None:
            return solved
    stats["backtracks"] += 1
    return None


def count_solutions(state: dict[str, object], limit: int, count_ref: dict[str, int]) -> None:
    if count_ref["count"] >= limit:
        return
    current = clone_state(state)
    dummy = {
        "givens": 0,
        "blanks": 0,
        "forcedMoves": 0,
        "guessedMoves": 0,
        "recursiveNodes": 0,
        "backtracks": 0,
        "maxDepth": 0,
    }
    if not propagate_singles(current, dummy):
        return
    best = select_unfilled_cell(current)
    if best is None:
        count_ref["count"] += 1
        return
    for digit in digits(best["mask"]):
        if count_ref["count"] >= limit:
            return
        next_state = clone_state(current)
        if place(next_state, best["index"], digit):
            count_solutions(next_state, limit, count_ref)


def unit_complete(values: list[int]) -> bool:
    seen = 0
    for value in values:
        if value < 1 or value > 9:
            return False
        bit = digit_mask(value)
        if seen & bit:
            return False
        seen |= bit
    return seen == ALL


def replay_moves_are_legal(puzzle_cells: list[int], moves: list[dict[str, object]]) -> bool:
    init = state_from_puzzle(puzzle_cells)
    if "error" in init:
        return False
    state: dict[str, object] = init["state"]  # type: ignore[assignment]
    cells: list[int] = state["cells"]  # type: ignore[assignment]
    for move in moves:
        index = int(move["index"])
        value = int(move["value"])
        if cells[index] != 0:
            return False
        mask_now = candidates(state, index)
        if mask_now != int(move["candidates_mask"]):
            return False
        if not (mask_now & digit_mask(value)):
            return False
        if bool(move["forced"]) and mask_now.bit_count() != 1:
            return False
        if not place(state, index, value):
            return False
    return True


def summarize_moves(moves: list[dict[str, object]], limit: int) -> str:
    if not moves:
        return "no placements were needed"
    parts: list[str] = []
    for move in moves[:limit]:
        index = int(move["index"])
        row = index // 9 + 1
        col = index % 9 + 1
        mode = "forced" if move["forced"] else "guess"
        parts.append(f"r{row}c{col}={move['value']}: {mode}")
    if len(moves) > limit:
        parts.append(f"... and {len(moves) - limit} more placements")
    return ", ".join(parts)


def term_text(term) -> str | None:
    if isinstance(term, Literal):
        return term.lexical
    return getattr(term, "value", None)


def compute_report(term) -> dict[str, object] | None:
    raw = term_text(term)
    if raw is None:
        return None
    cached = REPORT_CACHE.get(raw)
    if cached is not None:
        return cached

    parsed = parse_puzzle(raw)
    if "error" in parsed:
        report = {"status": "invalid-input", "error": parsed["error"], "raw": raw, "normalized": None}
        REPORT_CACHE[raw] = report
        return report

    cells: list[int] = parsed["cells"]  # type: ignore[assignment]
    normalized = "".join(str(value) for value in cells)
    init = state_from_puzzle(cells)
    if "error" in init:
        report = {
            "status": "illegal-clues",
            "error": init["error"],
            "raw": raw,
            "normalized": normalized,
            "givens": sum(1 for value in cells if value != 0),
            "blanks": sum(1 for value in cells if value == 0),
            "puzzleText": format_board(cells),
        }
        REPORT_CACHE[raw] = report
        return report

    initial: dict[str, object] = init["state"]  # type: ignore[assignment]
    stats = {
        "givens": sum(1 for value in cells if value != 0),
        "blanks": sum(1 for value in cells if value == 0),
        "forcedMoves": 0,
        "guessedMoves": 0,
        "recursiveNodes": 0,
        "backtracks": 0,
        "maxDepth": 0,
    }
    solved = solve(initial, stats, 0)
    if solved is None:
        report = {
            "status": "unsatisfiable",
            "raw": raw,
            "normalized": normalized,
            "givens": stats["givens"],
            "blanks": stats["blanks"],
            "recursiveNodes": stats["recursiveNodes"],
            "backtracks": stats["backtracks"],
            "puzzleText": format_board(cells),
        }
        REPORT_CACHE[raw] = report
        return report

    count_ref = {"count": 0}
    count_solutions(initial, 2, count_ref)
    solved_cells: list[int] = solved["cells"]  # type: ignore[assignment]
    moves: list[dict[str, object]] = solved["moves"]  # type: ignore[assignment]
    rows_complete = all(unit_complete(solved_cells[row * 9 : row * 9 + 9]) for row in range(9))
    cols_complete = all(unit_complete([solved_cells[row * 9 + col] for row in range(9)]) for col in range(9))
    boxes_complete = all(
        unit_complete([
            solved_cells[((box // 3) * 3 + delta_row) * 9 + (box % 3) * 3 + delta_col]
            for delta_row in range(3)
            for delta_col in range(3)
        ])
        for box in range(9)
    )
    proof_path_guess_count = sum(1 for move in moves if not move["forced"])
    report = {
        "status": "ok",
        "raw": raw,
        "normalized": normalized,
        "givens": stats["givens"],
        "blanks": stats["blanks"],
        "forcedMoves": stats["forcedMoves"],
        "guessedMoves": stats["guessedMoves"],
        "recursiveNodes": stats["recursiveNodes"],
        "backtracks": stats["backtracks"],
        "maxDepth": stats["maxDepth"],
        "unique": count_ref["count"] == 1,
        "solution": "".join(str(value) for value in solved_cells),
        "puzzleText": format_board(cells),
        "solutionText": format_board(solved_cells),
        "moveSummary": summarize_moves(moves, 8),
        "moveCount": len(moves),
        "givensPreserved": all(value == 0 or value == solved_cells[index] for index, value in enumerate(cells)),
        "noBlanks": all(1 <= value <= 9 for value in solved_cells),
        "rowsComplete": rows_complete,
        "colsComplete": cols_complete,
        "boxesComplete": boxes_complete,
        "replayLegal": replay_moves_are_legal(cells, moves),
        "storyConsistent": stats["recursiveNodes"] >= 1
        and stats["maxDepth"] <= stats["blanks"]
        and len(moves) == stats["blanks"]
        and proof_path_guess_count <= stats["guessedMoves"],
    }
    REPORT_CACHE[raw] = report
    return report


def report_field_as_term(report: dict[str, object], field: str):
    string_fields = {
        "status": "status",
        "error": "error",
        "normalizedPuzzle": "normalized",
        "solution": "solution",
        "puzzleText": "puzzleText",
        "solutionText": "solutionText",
        "moveSummary": "moveSummary",
    }
    if field in string_fields:
        value = report.get(string_fields[field])
        return string_lit(str(value)) if value is not None else None

    text_fields = {
        "givensPreservedText": "givensPreserved",
        "noBlanksText": "noBlanks",
        "rowsCompleteText": "rowsComplete",
        "colsCompleteText": "colsComplete",
        "boxesCompleteText": "boxesComplete",
        "replayLegalText": "replayLegal",
        "storyConsistentText": "storyConsistent",
    }
    if field in text_fields:
        value = report.get(text_fields[field])
        return string_lit("OK" if value is True else "failed") if value is not None else None

    if field in {
        "unique",
        "givensPreserved",
        "noBlanks",
        "rowsComplete",
        "colsComplete",
        "boxesComplete",
        "replayLegal",
        "storyConsistent",
    }:
        value = report.get(field)
        return bool_lit(bool(value)) if value is not None else None

    if field in {
        "givens",
        "blanks",
        "forcedMoves",
        "guessedMoves",
        "recursiveNodes",
        "backtracks",
        "maxDepth",
        "moveCount",
    }:
        value = report.get(field)
        return int_lit(int(value)) if value is not None else None
    return None


def make_field_handler(field: str):
    def handler(ctx):
        subject = ctx.engine.apply_subst(ctx.goal.s, ctx.subst)
        report = compute_report(subject)
        if report is None:
            return []
        term = report_field_as_term(report, field)
        if term is None:
            return []
        nxt = ctx.unify_term(ctx.goal.o, term, ctx.subst)
        return [] if nxt is None else [nxt]

    return handler


def register(api) -> None:
    for field in (
        "status",
        "error",
        "normalizedPuzzle",
        "solution",
        "givens",
        "blanks",
        "forcedMoves",
        "guessedMoves",
        "recursiveNodes",
        "backtracks",
        "maxDepth",
        "unique",
        "givensPreserved",
        "noBlanks",
        "rowsComplete",
        "colsComplete",
        "boxesComplete",
        "replayLegal",
        "storyConsistent",
        "givensPreservedText",
        "noBlanksText",
        "rowsCompleteText",
        "colsCompleteText",
        "boxesCompleteText",
        "replayLegalText",
        "storyConsistentText",
        "moveSummary",
        "puzzleText",
        "solutionText",
        "moveCount",
    ):
        api["registerBuiltin"](NS + field, make_field_handler(field))

