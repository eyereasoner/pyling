"""Builtin predicate registry for pyling."""
from __future__ import annotations

import hashlib
import json
import math
import re
import uuid
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_FLOOR, getcontext
from typing import Callable, Iterable, Mapping, MutableMapping
from urllib.parse import quote

from .deref import fetch_http_document, strip_fragment
from .terms import (
    CRYPTO_NS,
    DT_NS,
    LIST_NS,
    LOG_NS,
    MATH_NS,
    RDF_FIRST,
    RDF_REST,
    RDF_NS,
    RDF_NIL,
    STRING_NS,
    TIME_NS,
    XSD_NS,
    Blank,
    GraphTerm,
    Iri,
    ListTerm,
    Literal,
    OpenListTerm,
    Term,
    Triple,
    Var,
    bool_value,
    literal_datatype,
    literal_from_python,
    literal_language,
    numeric_value,
    quote_string,
)

getcontext().prec = 80
Subst = dict[str, Term]
BuiltinHandler = Callable[["BuiltinContext"], list[Subst]]


@dataclass(slots=True)
class BuiltinContext:
    goal: Triple
    subst: Subst
    engine: object

    def unify_term(self, a: Term, b: Term, subst: Subst | None = None) -> Subst | None:
        return self.engine.unify_term(a, b, subst or self.subst)  # type: ignore[attr-defined]

    def term_to_n3(self, term: Term) -> str:
        return self.engine.term_to_n3(term)  # type: ignore[attr-defined]

    def intern_literal(self, value: str, datatype: str | None = None) -> Literal:
        return Literal(value, datatype or XSD_NS + "string")

    def intern_iri(self, value: str) -> Iri:
        return Iri(value)


_REGISTRY: dict[str, BuiltinHandler] = {}


def register_builtin(iri: str, handler: BuiltinHandler) -> BuiltinHandler:
    if not callable(handler):
        raise TypeError("builtin handler must be callable")
    _REGISTRY[str(iri)] = handler
    return handler


def unregister_builtin(iri: str) -> bool:
    return _REGISTRY.pop(str(iri), None) is not None


def list_builtin_iris() -> list[str]:
    return sorted(_REGISTRY)


def get_builtin(iri: str) -> BuiltinHandler | None:
    return _REGISTRY.get(iri)


def register_builtin_module(module: object, origin: str | None = None) -> bool:
    """Accept Python modules or dicts with a register/register_builtins function."""
    fn = None
    if isinstance(module, Mapping):
        fn = module.get("register") or module.get("register_builtins") or module.get("default")
    else:
        fn = getattr(module, "register", None) or getattr(module, "register_builtins", None)
    if not callable(fn):
        raise TypeError("builtin module must expose register() or register_builtins()")
    fn({"registerBuiltin": register_builtin, "unregisterBuiltin": unregister_builtin})
    return True


def _term_num(t: Term) -> Decimal | None:
    return numeric_value(t)


def _term_int(t: Term) -> int | None:
    if isinstance(t, Literal) and literal_datatype(t) == XSD_NS + "integer":
        try:
            text = t.lexical
            sign = -1 if text.startswith("-") else 1
            if text[:1] in {"+", "-"}:
                text = text[1:]
            if not text or not text.isdigit():
                return None
            value = 0
            for offset in range(0, len(text), 9):
                chunk = text[offset : offset + 9]
                value = value * (10 ** len(chunk)) + int(chunk)
            return sign * value
        except ValueError:
            return None
    return None


def _int_lexical(value: int) -> str:
    """Render arbitrary-size integers without Python's int-to-string limit."""
    if value == 0:
        return "0"
    sign = "-" if value < 0 else ""
    value = abs(value)
    chunks: list[int] = []
    base = 1_000_000_000
    while value:
        value, chunk = divmod(value, base)
        chunks.append(chunk)
    return sign + str(chunks[-1]) + "".join(f"{chunk:09d}" for chunk in reversed(chunks[:-1]))


def _int_lit(value: int) -> Literal:
    return Literal(_int_lexical(value), XSD_NS + "integer", bare=True)


def _term_str(t: Term) -> str | None:
    if isinstance(t, Literal):
        return t.lexical
    if isinstance(t, Iri):
        return t.value
    return None


def _datetime_value(term: Term):
    if not isinstance(term, Literal):
        return None
    datatype = literal_datatype(term)
    if datatype not in {XSD_NS + "date", XSD_NS + "dateTime", XSD_NS + "dateTimeStamp"}:
        return None
    import datetime as _dt

    lexical = term.lexical
    if datatype == XSD_NS + "date":
        lexical += "T00:00:00+00:00"
    elif lexical.endswith("Z"):
        lexical = lexical[:-1] + "+00:00"
    try:
        value = _dt.datetime.fromisoformat(lexical)
    except ValueError:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=_dt.timezone.utc)
    return value


def _duration_seconds(term: Term) -> Decimal | None:
    if not isinstance(term, Literal) or literal_datatype(term) != XSD_NS + "duration":
        return None
    match = re.fullmatch(
        r"(?P<sign>-)?P(?:(?P<years>[0-9.]+)Y)?(?:(?P<months>[0-9.]+)M)?"
        r"(?:(?P<weeks>[0-9.]+)W)?(?:(?P<days>[0-9.]+)D)?"
        r"(?:T(?:(?P<hours>[0-9.]+)H)?(?:(?P<minutes>[0-9.]+)M)?"
        r"(?:(?P<seconds>[0-9.]+)S)?)?",
        term.lexical,
    )
    if match is None:
        return None
    values = {
        name: Decimal(match.group(name) or "0")
        for name in ("years", "months", "weeks", "days", "hours", "minutes", "seconds")
    }
    days = (
        values["years"] * Decimal("365.2425")
        + values["months"] * Decimal("30.436875")
        + values["weeks"] * 7
        + values["days"]
    )
    total = days * 86400 + values["hours"] * 3600 + values["minutes"] * 60 + values["seconds"]
    return -total if match.group("sign") else total


def _comparable_num(term: Term) -> Decimal | None:
    number = _term_num(term)
    if number is not None:
        return number
    duration = _duration_seconds(term)
    if duration is not None:
        return duration
    date = _datetime_value(term)
    if date is not None:
        return Decimal(str(date.timestamp()))
    return None


def _num_lit(n: Decimal) -> Literal:
    if n == n.to_integral_value():
        return Literal(str(int(n)), XSD_NS + "integer", bare=True)
    s = format(n.normalize(), "f")
    if "." not in s:
        s += ".0"
    return Literal(s, XSD_NS + "decimal", bare=True)


_NUMERIC_TYPE_RANK = {
    XSD_NS + "integer": 0,
    XSD_NS + "decimal": 1,
    XSD_NS + "float": 2,
    XSD_NS + "double": 3,
}


def _promoted_numeric_datatype(terms: Iterable[Term]) -> str:
    datatypes = [literal_datatype(t) for t in terms if isinstance(t, Literal)]
    return max(datatypes, key=lambda dt: _NUMERIC_TYPE_RANK.get(dt, 0), default=XSD_NS + "integer")


def _typed_num_lit(n: Decimal, datatype: str, *, float_style: bool = False) -> Literal:
    if datatype == XSD_NS + "integer":
        lexical = str(int(n))
    elif float_style:
        lexical = repr(float(n))
    elif n == n.to_integral_value():
        lexical = str(int(n))
    else:
        lexical = format(n.normalize(), "f")
    return Literal(lexical, datatype, bare=True)


def _bool_lit(v: bool) -> Literal:
    return Literal("true" if v else "false", XSD_NS + "boolean", bare=True)


def _bind_or_test(ctx: BuiltinContext, expected: Term, actual: Term) -> list[Subst]:
    nxt = ctx.unify_term(expected, actual, ctx.subst)
    return [] if nxt is None else [nxt]


def _bind_numeric_or_test(ctx: BuiltinContext, expected: Term, actual: Literal) -> list[Subst]:
    expected_value = ctx.engine.apply_subst(expected, ctx.subst)  # type: ignore[attr-defined]
    expected_num = numeric_value(expected_value)
    actual_num = numeric_value(actual)
    if expected_num is not None and actual_num is not None:
        return [ctx.subst] if math.isclose(float(expected_num), float(actual_num), rel_tol=1e-12, abs_tol=1e-12) else []
    return _bind_or_test(ctx, expected, actual)


def _list_elems(ctx: BuiltinContext, t: Term) -> list[Term] | None:
    t = ctx.engine.apply_subst(t, ctx.subst)  # type: ignore[attr-defined]
    if isinstance(t, ListTerm):
        return list(t.elems)
    if isinstance(t, Iri) and t.value == RDF_NIL:
        return []
    # Recover an RDF collection from rdf:first/rest explicit facts when possible.
    return ctx.engine.rdf_collection_to_list(t)  # type: ignore[attr-defined]


def _known_list_terms(ctx: BuiltinContext) -> list[ListTerm]:
    """Enumerate collection literals already present in the active fact set."""
    found: list[ListTerm] = []
    seen: set[ListTerm] = set()

    def visit(term: Term) -> None:
        if isinstance(term, ListTerm):
            if term not in seen:
                seen.add(term)
                found.append(term)
            for item in term.elems:
                visit(item)
        elif isinstance(term, OpenListTerm):
            for item in term.prefix:
                visit(item)
        elif isinstance(term, GraphTerm):
            for triple in term.triples:
                visit(triple.s)
                visit(triple.p)
                visit(triple.o)

    for triple in ctx.engine.facts:  # type: ignore[attr-defined]
        visit(triple.s)
        visit(triple.o)
    return found


def _math_cmp(op: Callable[[Decimal, Decimal], bool]) -> BuiltinHandler:
    def handler(ctx: BuiltinContext) -> list[Subst]:
        subject = ctx.engine.apply_subst(ctx.goal.s, ctx.subst)  # type: ignore[attr-defined]
        obj = ctx.engine.apply_subst(ctx.goal.o, ctx.subst)  # type: ignore[attr-defined]
        if isinstance(subject, ListTerm) and len(subject.elems) == 2:
            left, right = subject.elems
        else:
            left, right = subject, obj
        a = _comparable_num(left)
        b = _comparable_num(right)
        if a is None or b is None:
            return []
        return [ctx.subst] if op(a, b) else []
    return handler


def _math_equal(ctx: BuiltinContext) -> list[Subst]:
    subject = ctx.engine.apply_subst(ctx.goal.s, ctx.subst)  # type: ignore[attr-defined]
    obj = ctx.engine.apply_subst(ctx.goal.o, ctx.subst)  # type: ignore[attr-defined]
    left, right = subject.elems if isinstance(subject, ListTerm) and len(subject.elems) == 2 else (subject, obj)
    a = _comparable_num(left)
    b = _comparable_num(right)
    return [ctx.subst] if a is not None and b is not None and a == b else []


def _math_not_equal(ctx: BuiltinContext) -> list[Subst]:
    subject = ctx.engine.apply_subst(ctx.goal.s, ctx.subst)  # type: ignore[attr-defined]
    obj = ctx.engine.apply_subst(ctx.goal.o, ctx.subst)  # type: ignore[attr-defined]
    left, right = subject.elems if isinstance(subject, ListTerm) and len(subject.elems) == 2 else (subject, obj)
    a = _comparable_num(left)
    b = _comparable_num(right)
    return [ctx.subst] if a is not None and b is not None and a != b else []


def _log_equal(ctx: BuiltinContext) -> list[Subst]:
    unified = ctx.unify_term(ctx.goal.s, ctx.goal.o, ctx.subst)
    return [] if unified is None else [unified]


def _log_not_equal(ctx: BuiltinContext) -> list[Subst]:
    return [] if _log_equal(ctx) else [ctx.subst]


def _math_sum(ctx: BuiltinContext) -> list[Subst]:
    elems = _list_elems(ctx, ctx.goal.s)
    if elems is None:
        return []
    values = [ctx.engine.apply_subst(e, ctx.subst) for e in elems]  # type: ignore[attr-defined]
    if len(values) == 2:
        for date_term, duration_term in (values, reversed(values)):
            date = _datetime_value(date_term)
            seconds = _duration_seconds(duration_term)
            if date is not None and seconds is not None and isinstance(date_term, Literal):
                import datetime as _dt

                result = date + _dt.timedelta(seconds=float(seconds))
                datatype = literal_datatype(date_term)
                lexical = result.date().isoformat() if datatype == XSD_NS + "date" else result.isoformat()
                return _bind_or_test(ctx, ctx.goal.o, Literal(lexical, datatype))
    datatype = _promoted_numeric_datatype(values)
    if datatype == XSD_NS + "integer":
        ints = [_term_int(e) for e in values]
        if all(i is not None for i in ints):
            return _bind_or_test(ctx, ctx.goal.o, _int_lit(sum(ints)))  # type: ignore[arg-type]
    total = Decimal(0)
    numeric_values: list[Decimal] = []
    for e in values:
        n = _term_num(e)
        if n is None:
            return []
        numeric_values.append(n)
        total += n
    if total and any(value < 0 for value in numeric_values) and any(value > 0 for value in numeric_values):
        scale = max(abs(value) for value in numeric_values)
        if scale and abs(total) <= scale * Decimal("1e-70"):
            total = Decimal(0)
    return _bind_or_test(ctx, ctx.goal.o, _typed_num_lit(total, datatype))


def _math_product(ctx: BuiltinContext) -> list[Subst]:
    elems = _list_elems(ctx, ctx.goal.s)
    if elems is None:
        return []
    values = [ctx.engine.apply_subst(e, ctx.subst) for e in elems]  # type: ignore[attr-defined]
    datatype = _promoted_numeric_datatype(values)
    if datatype == XSD_NS + "integer":
        ints = [_term_int(e) for e in values]
        if all(i is not None for i in ints):
            total_int = 1
            for i in ints:
                total_int *= i  # type: ignore[operator]
            return _bind_or_test(ctx, ctx.goal.o, _int_lit(total_int))
    total = Decimal(1)
    for e in values:
        n = _term_num(e)
        if n is None:
            return []
        total *= n
    return _bind_or_test(ctx, ctx.goal.o, _typed_num_lit(total, datatype))


def _binary_num(ctx: BuiltinContext, fn: Callable[[Decimal, Decimal], Decimal]) -> list[Subst]:
    elems = _list_elems(ctx, ctx.goal.s)
    if not elems or len(elems) != 2:
        return []
    a = _term_num(ctx.engine.apply_subst(elems[0], ctx.subst))  # type: ignore[attr-defined]
    b = _term_num(ctx.engine.apply_subst(elems[1], ctx.subst))  # type: ignore[attr-defined]
    if a is None or b is None:
        return []
    try:
        return _bind_or_test(ctx, ctx.goal.o, _typed_num_lit(fn(a, b), _promoted_numeric_datatype(elems)))
    except Exception:
        return []


def _unary_num(ctx: BuiltinContext, fn: Callable[[Decimal], Decimal]) -> list[Subst]:
    a = _term_num(ctx.engine.apply_subst(ctx.goal.s, ctx.subst))  # type: ignore[attr-defined]
    if a is None:
        return []
    try:
        subject = ctx.engine.apply_subst(ctx.goal.s, ctx.subst)  # type: ignore[attr-defined]
        datatype = literal_datatype(subject) if isinstance(subject, Literal) else XSD_NS + "decimal"
        return _bind_or_test(ctx, ctx.goal.o, _typed_num_lit(fn(a), datatype))
    except Exception:
        return []


def _math_difference(ctx: BuiltinContext) -> list[Subst]:
    elems = _list_elems(ctx, ctx.goal.s)
    if elems is not None and len(elems) == 2:
        values = [ctx.engine.apply_subst(e, ctx.subst) for e in elems]  # type: ignore[attr-defined]
        left_date = _datetime_value(values[0])
        right_date = _datetime_value(values[1])
        if left_date is not None and right_date is not None:
            seconds = Decimal(str((left_date - right_date).total_seconds()))
            lexical = format(abs(seconds).normalize(), "f")
            if "." not in lexical:
                lexical = str(int(abs(seconds)))
            duration = ("-" if seconds < 0 else "") + f"PT{lexical}S"
            return _bind_or_test(ctx, ctx.goal.o, Literal(duration, XSD_NS + "duration"))
        duration = _duration_seconds(values[1])
        if left_date is not None and duration is not None and isinstance(values[0], Literal):
            import datetime as _dt

            result = left_date - _dt.timedelta(seconds=float(duration))
            datatype = literal_datatype(values[0])
            lexical = result.date().isoformat() if datatype == XSD_NS + "date" else result.isoformat()
            return _bind_or_test(ctx, ctx.goal.o, Literal(lexical, datatype))
        ints = [_term_int(value) for value in values]
        if all(value is not None for value in ints):
            return _bind_or_test(ctx, ctx.goal.o, _int_lit(ints[0] - ints[1]))  # type: ignore[operator]
    return _binary_num(ctx, lambda a, b: a - b)


def _math_quotient(ctx: BuiltinContext) -> list[Subst]:
    elems = _list_elems(ctx, ctx.goal.s)
    if elems is None or len(elems) != 2:
        return []
    a = _term_num(ctx.engine.apply_subst(elems[0], ctx.subst))  # type: ignore[attr-defined]
    b = _term_num(ctx.engine.apply_subst(elems[1], ctx.subst))  # type: ignore[attr-defined]
    if a is None or b is None or b == 0:
        return []
    result = a / b
    datatype = _promoted_numeric_datatype(elems)
    if datatype == XSD_NS + "integer" and result != result.to_integral_value():
        datatype = XSD_NS + "decimal"
    return _bind_or_test(ctx, ctx.goal.o, _typed_num_lit(result, datatype))


def _math_remainder(ctx: BuiltinContext) -> list[Subst]:
    elems = _list_elems(ctx, ctx.goal.s)
    if elems is not None and len(elems) == 2:
        values = [ctx.engine.apply_subst(e, ctx.subst) for e in elems]  # type: ignore[attr-defined]
        ints = [_term_int(value) for value in values]
        if all(value is not None for value in ints) and ints[1] != 0:
            quotient = abs(ints[0]) // abs(ints[1])  # type: ignore[arg-type]
            if (ints[0] < 0) != (ints[1] < 0):
                quotient = -quotient
            return _bind_or_test(ctx, ctx.goal.o, _int_lit(ints[0] - quotient * ints[1]))  # type: ignore[operator]
    return _binary_num(ctx, lambda a, b: a % b)


def _math_integer_quotient(ctx: BuiltinContext) -> list[Subst]:
    elems = _list_elems(ctx, ctx.goal.s)
    if elems is not None and len(elems) == 2:
        values = [ctx.engine.apply_subst(e, ctx.subst) for e in elems]  # type: ignore[attr-defined]
        ints = [_term_int(value) for value in values]
        if all(value is not None for value in ints) and ints[1] != 0:
            quotient = abs(ints[0]) // abs(ints[1])  # type: ignore[arg-type]
            if (ints[0] < 0) != (ints[1] < 0):
                quotient = -quotient
            return _bind_or_test(ctx, ctx.goal.o, _int_lit(quotient))
    return _binary_num(ctx, lambda a, b: Decimal(int(a / b)))


def _math_exponentiation(ctx: BuiltinContext) -> list[Subst]:
    elems = _list_elems(ctx, ctx.goal.s)
    if elems is not None and len(elems) == 2:
        values = [ctx.engine.apply_subst(e, ctx.subst) for e in elems]  # type: ignore[attr-defined]
        ints = [_term_int(value) for value in values]
        if all(value is not None for value in ints) and ints[1] >= 0:
            return _bind_or_test(ctx, ctx.goal.o, _int_lit(pow(ints[0], ints[1])))  # type: ignore[arg-type]
        base = _term_num(values[0])
        result_term = ctx.engine.apply_subst(ctx.goal.o, ctx.subst)  # type: ignore[attr-defined]
        result = _term_num(result_term)
        if base is not None and isinstance(values[1], Var) and result is not None:
            base_float = float(base)
            result_float = float(result)
            if base_float > 0.0 and base_float != 1.0 and result_float > 0.0:
                exponent = math.log(result_float) / math.log(base_float)
                rounded = round(exponent)
                if math.isclose(exponent, rounded, rel_tol=1e-12, abs_tol=1e-12):
                    return _bind_or_test(ctx, elems[1], _int_lit(rounded))
                return _bind_or_test(
                    ctx,
                    elems[1],
                    _typed_num_lit(Decimal(str(exponent)), XSD_NS + "decimal"),
                )

    def exponentiate(a: Decimal, b: Decimal) -> Decimal:
        if b == b.to_integral_value():
            return a ** int(b)
        if a < 0 and abs(a) <= Decimal("1e-15"):
            # Fractional powers use binary floating-point, matching Eyeling.
            # Cancellation around an exact zero can leave a tiny negative
            # Decimal residue before this conversion; treat it as signed zero.
            a = Decimal(0)
        return Decimal(str(pow(float(a), float(b))))
    return _binary_num(ctx, exponentiate)


def _math_negation(ctx: BuiltinContext) -> list[Subst]:
    subject = ctx.engine.apply_subst(ctx.goal.s, ctx.subst)  # type: ignore[attr-defined]
    obj = ctx.engine.apply_subst(ctx.goal.o, ctx.subst)  # type: ignore[attr-defined]
    a, b = _term_num(subject), _term_num(obj)
    if a is None and b is None:
        return [ctx.subst] if isinstance(subject, Var) and isinstance(obj, Var) else []
    if a is None and b is not None:
        datatype = literal_datatype(obj) if isinstance(obj, Literal) else XSD_NS + "integer"
        return _bind_or_test(ctx, ctx.goal.s, _typed_num_lit(-b, datatype))
    if a is None:
        return []
    datatype = literal_datatype(subject) if isinstance(subject, Literal) else XSD_NS + "integer"
    return _bind_or_test(ctx, ctx.goal.o, _typed_num_lit(-a, datatype))


def _math_absolute_value(ctx: BuiltinContext) -> list[Subst]:
    return _unary_num(ctx, abs)


def _math_rounded(ctx: BuiltinContext) -> list[Subst]:
    subject = ctx.engine.apply_subst(ctx.goal.s, ctx.subst)  # type: ignore[attr-defined]
    value = _term_num(subject)
    if value is None or not isinstance(subject, Literal):
        return []
    rounded = (value + Decimal("0.5")).to_integral_value(rounding=ROUND_FLOOR)
    datatype = XSD_NS + "integer" if subject.bare else literal_datatype(subject)
    return _bind_or_test(ctx, ctx.goal.o, _typed_num_lit(rounded, datatype))


def _list_first(ctx: BuiltinContext) -> list[Subst]:
    subject = ctx.engine.apply_subst(ctx.goal.s, ctx.subst)  # type: ignore[attr-defined]
    if isinstance(subject, Var):
        results: list[Subst] = []
        for candidate in _known_list_terms(ctx):
            if not candidate.elems:
                continue
            nxt = ctx.unify_term(ctx.goal.s, candidate, ctx.subst)
            if nxt is not None:
                nxt = ctx.engine.unify_term(ctx.goal.o, candidate.elems[0], nxt)  # type: ignore[attr-defined]
            if nxt is not None:
                results.append(nxt)
        return results
    elems = _list_elems(ctx, ctx.goal.s)
    if elems is None or not elems:
        return []
    nxt = _unify_builtin_value(ctx, ctx.goal.o, elems[0], ctx.subst)
    return [] if nxt is None else [nxt]


def _list_rest(ctx: BuiltinContext) -> list[Subst]:
    subject = ctx.engine.apply_subst(ctx.goal.s, ctx.subst)  # type: ignore[attr-defined]
    if isinstance(subject, Var):
        results: list[Subst] = []
        for candidate in _known_list_terms(ctx):
            if not candidate.elems:
                continue
            nxt = ctx.unify_term(ctx.goal.s, candidate, ctx.subst)
            if nxt is not None:
                nxt = ctx.engine.unify_term(ctx.goal.o, ListTerm(candidate.elems[1:]), nxt)  # type: ignore[attr-defined]
            if nxt is not None:
                results.append(nxt)
        return results
    elems = _list_elems(ctx, ctx.goal.s)
    if not elems:
        return []
    return _bind_list_or_test(ctx, ctx.goal.o, elems[1:])


def _list_length(ctx: BuiltinContext) -> list[Subst]:
    elems = _list_elems(ctx, ctx.goal.s)
    if elems is None:
        return []
    return _bind_or_test(ctx, ctx.goal.o, Literal(str(len(elems)), XSD_NS + "integer", bare=True))


def _list_in(ctx: BuiltinContext) -> list[Subst]:
    item = ctx.engine.apply_subst(ctx.goal.s, ctx.subst)  # type: ignore[attr-defined]
    elems = _list_elems(ctx, ctx.goal.o)
    if elems is None:
        return []
    out: list[Subst] = []
    for e in elems:
        nxt = ctx.unify_term(item, e, ctx.subst)
        if nxt is not None:
            out.append(nxt)
    return out


def _list_member(ctx: BuiltinContext) -> list[Subst]:
    elems = _list_elems(ctx, ctx.goal.s)
    if elems is None:
        return []
    out: list[Subst] = []
    for e in elems:
        nxt = ctx.unify_term(ctx.goal.o, e, ctx.subst)
        if nxt is not None:
            out.append(nxt)
    return out


def _list_append(ctx: BuiltinContext) -> list[Subst]:
    subject = ctx.engine.apply_subst(ctx.goal.s, ctx.subst)  # type: ignore[attr-defined]
    if not isinstance(subject, ListTerm):
        return []
    result = ctx.engine.apply_subst(ctx.goal.o, ctx.subst)  # type: ignore[attr-defined]
    if isinstance(result, ListTerm):
        def split(parts: tuple[Term, ...], remaining: tuple[Term, ...], subst: Subst) -> list[Subst]:
            if not parts:
                return [subst] if not remaining else []
            solutions: list[Subst] = []
            for width in range(len(remaining) + 1):
                nxt = ctx.engine.unify_term(parts[0], ListTerm(remaining[:width]), subst)  # type: ignore[attr-defined]
                if nxt is not None:
                    solutions.extend(split(parts[1:], remaining[width:], nxt))
            return solutions

        return split(subject.elems, result.elems, dict(ctx.subst))
    elems = list(subject.elems)
    merged: list[Term] = []
    for e in elems:
        sub = _list_elems(ctx, e)
        if sub is None:
            return []
        merged.extend(sub)
    return _bind_list_or_test(ctx, ctx.goal.o, merged, promote_int_decimal=True)


def _bind_list_or_test(ctx: BuiltinContext, expected: Term, actual: Iterable[Term], *, promote_int_decimal: bool = False) -> list[Subst]:
    actual_list = list(actual)
    expected_value = ctx.engine.apply_subst(expected, ctx.subst)  # type: ignore[attr-defined]
    recovered = _list_elems(ctx, expected_value)
    if recovered is not None and not isinstance(expected_value, Var):
        if len(recovered) != len(actual_list):
            return []
        current = dict(ctx.subst)
        for left, right in zip(recovered, actual_list):
            current = _unify_builtin_value(ctx, left, right, current, promote_int_decimal=promote_int_decimal)
            if current is None:
                return []
        return [current]
    return _bind_or_test(ctx, expected, ListTerm(actual_list))


def _unify_builtin_value(ctx: BuiltinContext, left: Term, right: Term, subst: Subst, *, promote_int_decimal: bool = False) -> Subst | None:
    left_value = ctx.engine.apply_subst(left, subst)  # type: ignore[attr-defined]
    right_value = ctx.engine.apply_subst(right, subst)  # type: ignore[attr-defined]
    left_list = _list_elems(ctx, left_value)
    right_list = _list_elems(ctx, right_value)
    if left_list is not None and right_list is not None:
        if len(left_list) != len(right_list):
            return None
        current = dict(subst)
        for a, b in zip(left_list, right_list):
            current = _unify_builtin_value(ctx, a, b, current, promote_int_decimal=promote_int_decimal)
            if current is None:
                return None
        return current
    if isinstance(left_value, Literal) and isinstance(right_value, Literal):
        left_num, right_num = numeric_value(left_value), numeric_value(right_value)
        datatypes = {literal_datatype(left_value), literal_datatype(right_value)}
        if promote_int_decimal and left_num is not None and right_num is not None and datatypes <= {XSD_NS + "integer", XSD_NS + "decimal"}:
            return dict(subst) if left_num == right_num else None
    return ctx.engine.unify_term(left, right, subst)  # type: ignore[attr-defined]


def _string_contains(ctx: BuiltinContext) -> list[Subst]:
    a = _term_str(ctx.engine.apply_subst(ctx.goal.s, ctx.subst))  # type: ignore[attr-defined]
    b = _term_str(ctx.engine.apply_subst(ctx.goal.o, ctx.subst))  # type: ignore[attr-defined]
    return [ctx.subst] if a is not None and b is not None and b in a else []


def _string_starts(ctx: BuiltinContext) -> list[Subst]:
    a = _term_str(ctx.engine.apply_subst(ctx.goal.s, ctx.subst))  # type: ignore[attr-defined]
    b = _term_str(ctx.engine.apply_subst(ctx.goal.o, ctx.subst))  # type: ignore[attr-defined]
    return [ctx.subst] if a is not None and b is not None and a.startswith(b) else []


def _string_ends(ctx: BuiltinContext) -> list[Subst]:
    a = _term_str(ctx.engine.apply_subst(ctx.goal.s, ctx.subst))  # type: ignore[attr-defined]
    b = _term_str(ctx.engine.apply_subst(ctx.goal.o, ctx.subst))  # type: ignore[attr-defined]
    return [ctx.subst] if a is not None and b is not None and a.endswith(b) else []


def _string_concatenation(ctx: BuiltinContext) -> list[Subst]:
    elems = _list_elems(ctx, ctx.goal.s)
    if elems is None:
        return []
    parts = []
    for e in elems:
        s = _term_str(ctx.engine.apply_subst(e, ctx.subst))  # type: ignore[attr-defined]
        if s is None:
            return []
        parts.append(s)
    return _bind_or_test(ctx, ctx.goal.o, Literal("".join(parts), XSD_NS + "string"))


def _string_format(ctx: BuiltinContext) -> list[Subst]:
    elems = _list_elems(ctx, ctx.goal.s)
    if not elems:
        return []
    fmt = _term_str(ctx.engine.apply_subst(elems[0], ctx.subst))  # type: ignore[attr-defined]
    if fmt is None:
        return []
    args = []
    for e in elems[1:]:
        v = ctx.engine.apply_subst(e, ctx.subst)  # type: ignore[attr-defined]
        if isinstance(v, Literal):
            integer = _term_int(v)
            number = _term_num(v)
            if integer is not None:
                args.append(integer)
            elif number is not None:
                args.append(float(number))
            else:
                args.append(v.lexical)
        else:
            args.append(ctx.term_to_n3(v))
    try:
        value = fmt % tuple(args)
    except Exception:
        try:
            value = fmt.format(*args)
        except Exception:
            return []
    return _bind_or_test(ctx, ctx.goal.o, Literal(value, XSD_NS + "string"))


def _string_replace(ctx: BuiltinContext) -> list[Subst]:
    elems = _list_elems(ctx, ctx.goal.s)
    if elems is None or len(elems) < 3:
        return []
    s = _term_str(ctx.engine.apply_subst(elems[0], ctx.subst))  # type: ignore[attr-defined]
    pat = _term_str(ctx.engine.apply_subst(elems[1], ctx.subst))  # type: ignore[attr-defined]
    rep = _term_str(ctx.engine.apply_subst(elems[2], ctx.subst))  # type: ignore[attr-defined]
    if s is None or pat is None or rep is None:
        return []
    try:
        def replacement(match: re.Match[str]) -> str:
            out: list[str] = []
            i = 0
            while i < len(rep):
                if rep[i] == "\\" and i + 1 < len(rep):
                    out.append(rep[i + 1])
                    i += 2
                elif rep[i] == "$" and i + 1 < len(rep) and rep[i + 1].isdigit():
                    j = i + 1
                    while j < len(rep) and rep[j].isdigit():
                        j += 1
                    index = int(rep[i + 1:j])
                    out.append(match.group(index) or "" if index <= (match.re.groups or 0) else "")
                    i = j
                else:
                    out.append(rep[i])
                    i += 1
            return "".join(out)
        value = re.sub(_xpath_regex(pat), replacement, s)
    except re.error:
        value = s.replace(pat, rep)
    return _bind_or_test(ctx, ctx.goal.o, Literal(value, XSD_NS + "string"))


def _string_matches(ctx: BuiltinContext) -> list[Subst]:
    a = _term_str(ctx.engine.apply_subst(ctx.goal.s, ctx.subst))  # type: ignore[attr-defined]
    b = _term_str(ctx.engine.apply_subst(ctx.goal.o, ctx.subst))  # type: ignore[attr-defined]
    if a is None or b is None:
        return []
    try:
        return [ctx.subst] if re.search(_xpath_regex(b), a) else []
    except re.error:
        return []


def _xpath_regex(pattern: str) -> str:
    """Translate the common XPath Unicode property escapes used by N3 tests."""
    replacements = {
        r"\p{Ll}": r"[^\W\d_]",
        r"\p{Lu}": r"[^\W\d_]",
        r"\p{L}": r"[^\W\d_]",
        r"\p{N}": r"\d",
        r"\p{P}": r"[^\w\s]",
        r"\p{Z}": r"\s",
    }
    for source, target in replacements.items():
        pattern = pattern.replace(source, target)
    return pattern


def _string_not_matches(ctx: BuiltinContext) -> list[Subst]:
    a = _term_str(ctx.engine.apply_subst(ctx.goal.s, ctx.subst))  # type: ignore[attr-defined]
    b = _term_str(ctx.engine.apply_subst(ctx.goal.o, ctx.subst))  # type: ignore[attr-defined]
    if a is None or b is None:
        return []
    try:
        return [ctx.subst] if re.search(_xpath_regex(b), a) is None else []
    except re.error:
        return []


def _log_uri(ctx: BuiltinContext) -> list[Subst]:
    s = ctx.engine.apply_subst(ctx.goal.s, ctx.subst)  # type: ignore[attr-defined]
    o = ctx.engine.apply_subst(ctx.goal.o, ctx.subst)  # type: ignore[attr-defined]
    if isinstance(s, Var) and isinstance(o, Var):
        return [ctx.subst]
    if isinstance(s, Var) and isinstance(o, Literal):
        if re.search(r'[\s<>"{}|^`\\]', o.lexical):
            return []
        return _bind_or_test(ctx, ctx.goal.s, Iri(o.lexical))
    if isinstance(s, Iri):
        return _bind_or_test(ctx, ctx.goal.o, Literal(s.value, XSD_NS + "string"))
    if isinstance(s, Literal):
        return _bind_or_test(ctx, ctx.goal.o, Iri(s.lexical))
    return []


def _log_dtlit(ctx: BuiltinContext) -> list[Subst]:
    subject = ctx.engine.apply_subst(ctx.goal.s, ctx.subst)  # type: ignore[attr-defined]
    obj = ctx.engine.apply_subst(ctx.goal.o, ctx.subst)  # type: ignore[attr-defined]
    if isinstance(subject, Var) and isinstance(obj, Var):
        return [ctx.subst]
    results: list[Subst] = []
    if isinstance(obj, Literal):
        pair = ListTerm((Literal(obj.lexical, XSD_NS + "string"), Iri(literal_datatype(obj))))
        nxt = ctx.unify_term(ctx.goal.s, pair, ctx.subst)
        if nxt is not None:
            results.append(nxt)
    elems = _list_elems(ctx, subject)
    if elems is None or len(elems) != 2:
        return results
    lex = ctx.engine.apply_subst(elems[0], ctx.subst)  # type: ignore[attr-defined]
    dt = ctx.engine.apply_subst(elems[1], ctx.subst)  # type: ignore[attr-defined]
    if not isinstance(lex, Literal) or not isinstance(dt, Iri):
        return results
    actual = Literal(lex.lexical, dt.value)
    if dt.value == RDF_NS + "langString" and isinstance(obj, Literal) and obj.lang and obj.lexical == lex.lexical:
        if ctx.subst not in results:
            results.append(ctx.subst)
        return results
    if isinstance(obj, Literal):
        probe = BuiltinContext(Triple(actual, Iri(LOG_NS + "equalTo"), obj), ctx.subst, ctx.engine)
        for solution in _log_equal(probe):
            if solution not in results:
                results.append(solution)
        return results
    for solution in _bind_or_test(ctx, ctx.goal.o, actual):
        if solution not in results:
            results.append(solution)
    return results


def _log_langlit(ctx: BuiltinContext) -> list[Subst]:
    subject = ctx.engine.apply_subst(ctx.goal.s, ctx.subst)  # type: ignore[attr-defined]
    obj = ctx.engine.apply_subst(ctx.goal.o, ctx.subst)  # type: ignore[attr-defined]
    if isinstance(subject, Var) and isinstance(obj, Var):
        return [ctx.subst]
    if isinstance(subject, Var) and isinstance(obj, Literal) and obj.lang:
        return _bind_or_test(ctx, ctx.goal.s, ListTerm((Literal(obj.lexical, XSD_NS + "string"), Literal(obj.lang.lower(), XSD_NS + "string"))))
    elems = _list_elems(ctx, subject)
    if elems is None or len(elems) != 2:
        return []
    lexical = ctx.engine.apply_subst(elems[0], ctx.subst)  # type: ignore[attr-defined]
    language = ctx.engine.apply_subst(elems[1], ctx.subst)  # type: ignore[attr-defined]
    if not isinstance(lexical, Literal) or not isinstance(language, Literal) or not language.lexical:
        return []
    return _bind_or_test(ctx, ctx.goal.o, Literal(lexical.lexical, lang=language.lexical.lower()))


def _log_raw_type(ctx: BuiltinContext) -> list[Subst]:
    s = ctx.engine.apply_subst(ctx.goal.s, ctx.subst)  # type: ignore[attr-defined]
    if isinstance(s, Iri):
        out = Iri(LOG_NS + "Other")
    elif isinstance(s, Blank):
        out = Iri(LOG_NS + "BlankNode")
    elif isinstance(s, Literal):
        out = Iri(LOG_NS + "Literal")
    elif isinstance(s, ListTerm):
        out = Iri(RDF_NS + "List")
    elif isinstance(s, GraphTerm):
        out = Iri(LOG_NS + "Formula")
    else:
        out = Iri(LOG_NS + "Other")
    return _bind_or_test(ctx, ctx.goal.o, out)


def _log_includes(ctx: BuiltinContext) -> list[Subst]:
    scope = ctx.engine.apply_subst(ctx.goal.s, ctx.subst)  # type: ignore[attr-defined]
    pattern = ctx.engine.apply_subst(ctx.goal.o, ctx.subst)  # type: ignore[attr-defined]
    if not isinstance(pattern, GraphTerm):
        return []
    if not isinstance(scope, GraphTerm):
        # Per Eyeling/EYE convention, any non-formula scope term -- an unbound
        # variable, a blank node used as a throwaway placeholder (`_:scope`),
        # or an arbitrary ground term used the same way (e.g. `1`) -- means
        # "search the ambient knowledge base" rather than a specific quoted
        # graph. Only bind the scope back to the matched candidate when it is
        # actually a variable the rule body can go on to reference.
        has_nested_formula = any(isinstance(term, GraphTerm) for triple in pattern.triples for term in (triple.s, triple.p, triple.o))
        if len(pattern.triples) == 1 and not has_nested_formula:
            return []
        candidates: list[GraphTerm] = []
        seen_candidates: set[GraphTerm] = set()

        def add_candidate(candidate: GraphTerm) -> None:
            if candidate in seen_candidates:
                return
            seen_candidates.add(candidate)
            candidates.append(candidate)
            for triple in candidate.triples:
                for term in (triple.s, triple.p, triple.o):
                    if isinstance(term, GraphTerm):
                        add_candidate(term)

        add_candidate(GraphTerm(ctx.engine.facts))  # type: ignore[attr-defined]
        for rule in [*ctx.engine.forward_rules, *ctx.engine.backward_rules]:  # type: ignore[attr-defined]
            add_candidate(GraphTerm(rule.premise))
            add_candidate(GraphTerm(rule.conclusion))
        old_facts = ctx.engine.facts  # type: ignore[attr-defined]
        results: list[Subst] = []
        try:
            for candidate in candidates:
                ctx.engine.facts = list(candidate.triples)  # type: ignore[attr-defined]
                for solution in ctx.engine.solve(list(pattern.triples), ctx.subst):  # type: ignore[attr-defined]
                    if isinstance(scope, Var):
                        bound = ctx.engine.unify_term(ctx.goal.s, candidate, solution)  # type: ignore[attr-defined]
                        if bound is not None:
                            results.append(bound)
                    else:
                        results.append(solution)
        finally:
            ctx.engine.facts = old_facts  # type: ignore[attr-defined]
        return results
    old_facts = ctx.engine.facts  # type: ignore[attr-defined]
    old_rule_fact_view = ctx.engine._rule_fact_view_active  # type: ignore[attr-defined]
    old_backward_rules = ctx.engine.backward_rules  # type: ignore[attr-defined]
    try:
        ctx.engine.facts = list(scope.triples)  # type: ignore[attr-defined]
        # An explicit quoted formula is a closed scope. Live top-level rules
        # remain executable in the ambient engine but are not members of this
        # formula unless represented by log:implies/log:impliedBy triples in it.
        ctx.engine._rule_fact_view_active = False  # type: ignore[attr-defined]
        ctx.engine.backward_rules = []  # type: ignore[attr-defined]
        return list(ctx.engine.solve(list(pattern.triples), ctx.subst))  # type: ignore[attr-defined]
    finally:
        ctx.engine.facts = old_facts  # type: ignore[attr-defined]
        ctx.engine._rule_fact_view_active = old_rule_fact_view  # type: ignore[attr-defined]
        ctx.engine.backward_rules = old_backward_rules  # type: ignore[attr-defined]


def _log_not_includes(ctx: BuiltinContext) -> list[Subst]:
    scope = ctx.engine.apply_subst(ctx.goal.s, ctx.subst)  # type: ignore[attr-defined]
    pattern = ctx.engine.apply_subst(ctx.goal.o, ctx.subst)  # type: ignore[attr-defined]
    if not isinstance(pattern, GraphTerm):
        return []
    if not isinstance(scope, GraphTerm):
        # Same "ambient knowledge base" convention as _log_includes above:
        # any non-formula scope (unbound variable, blank node placeholder,
        # or dummy ground term) searches everywhere, not just a literal
        # match against the scope term itself.
        solutions = ctx.engine.solve(list(pattern.triples), ctx.subst)  # type: ignore[attr-defined]
        return [] if next(solutions, None) is not None else [ctx.subst]
    return [] if _log_includes(ctx) else [ctx.subst]


def _document_to_formula(text: str, *, base_iri: str = "") -> GraphTerm:
    from .parser import parse_n3

    blank_prefix = "_:http_" + hashlib.sha256(base_iri.encode()).hexdigest()[:12] + "_"
    doc = parse_n3(text, base_iri=base_iri or None, blank_prefix=blank_prefix)
    triples = list(doc.triples)
    for rule in doc.forward_rules:
        conclusion: Term = (
            Literal("false", XSD_NS + "boolean", bare=True)
            if rule.is_fuse
            else GraphTerm(rule.conclusion)
        )
        triples.append(Triple(GraphTerm(rule.premise), Iri(LOG_NS + "implies"), conclusion))
    for rule in doc.backward_rules:
        triples.append(
            Triple(
                GraphTerm(rule.conclusion),
                Iri(LOG_NS + "impliedBy"),
                GraphTerm(rule.premise),
            )
        )
    return GraphTerm(triples)


def _dereference_formula(iri: str) -> GraphTerm | None:
    document = fetch_http_document(strip_fragment(iri))
    if document is None:
        return None
    try:
        return _document_to_formula(document.text, base_iri=document.url)
    except Exception:
        return None


def _log_content(ctx: BuiltinContext) -> list[Subst]:
    source = ctx.engine.apply_subst(ctx.goal.s, ctx.subst)  # type: ignore[attr-defined]
    if not isinstance(source, Iri):
        return []
    document = fetch_http_document(strip_fragment(source.value))
    if document is None:
        return []
    return _bind_or_test(ctx, ctx.goal.o, Literal(document.text, XSD_NS + "string"))


def _log_semantics(ctx: BuiltinContext) -> list[Subst]:
    source = ctx.engine.apply_subst(ctx.goal.s, ctx.subst)  # type: ignore[attr-defined]
    if isinstance(source, GraphTerm):
        return _bind_or_test(ctx, ctx.goal.o, source)
    if not isinstance(source, Iri):
        return []
    formula = _dereference_formula(source.value)
    if formula is None:
        return []
    formula = ctx.engine.standardize_term_apart(  # type: ignore[attr-defined]
        formula,
        scope_key="log:semantics:" + strip_fragment(source.value),
    )
    return _bind_or_test(ctx, ctx.goal.o, formula)


def _log_semantics_or_error(ctx: BuiltinContext) -> list[Subst]:
    source = ctx.engine.apply_subst(ctx.goal.s, ctx.subst)  # type: ignore[attr-defined]
    if not isinstance(source, Iri):
        return []
    formula = _dereference_formula(source.value)
    if formula is not None:
        formula = ctx.engine.standardize_term_apart(  # type: ignore[attr-defined]
            formula,
            scope_key="log:semantics:" + strip_fragment(source.value),
        )
    result: Term = (
        formula
        if formula is not None
        else Literal(
            f"error(dereference_or_parse_failed,{strip_fragment(source.value)})",
            XSD_NS + "string",
        )
    )
    return _bind_or_test(ctx, ctx.goal.o, result)


def _log_conclusion(ctx: BuiltinContext) -> list[Subst]:
    source = ctx.engine.apply_subst(ctx.goal.s, ctx.subst)  # type: ignore[attr-defined]
    if not isinstance(source, GraphTerm):
        return []
    from .parser import Document
    doc = Document(ctx.engine.prefixes.copy(), list(source.triples), [], [], [])  # type: ignore[attr-defined]
    nested = type(ctx.engine)(doc, {"include_input_facts_in_closure": True})
    result = nested.run()
    return _bind_or_test(ctx, ctx.goal.o, GraphTerm(result.facts))


def _log_skolem(ctx: BuiltinContext) -> list[Subst]:
    s = ctx.engine.apply_subst(ctx.goal.s, ctx.subst)  # type: ignore[attr-defined]
    key = ctx.term_to_n3(s)
    digest = hashlib.sha256((ctx.engine.skolem_salt + "|" + key).encode()).hexdigest()  # type: ignore[attr-defined]
    return _bind_or_test(ctx, ctx.goal.o, Iri("urn:uuid:" + str(uuid.UUID(digest[:32]))))


def _dt_datatype(ctx: BuiltinContext) -> list[Subst]:
    s = ctx.engine.apply_subst(ctx.goal.s, ctx.subst)  # type: ignore[attr-defined]
    if not isinstance(s, Literal):
        return []
    return _bind_or_test(ctx, ctx.goal.o, Iri(literal_datatype(s)))


def _dt_lexical_form(ctx: BuiltinContext) -> list[Subst]:
    s = ctx.engine.apply_subst(ctx.goal.s, ctx.subst)  # type: ignore[attr-defined]
    if not isinstance(s, Literal):
        return []
    return _bind_or_test(ctx, ctx.goal.o, Literal(s.lexical, XSD_NS + "string"))


def _dt_language(ctx: BuiltinContext) -> list[Subst]:
    s = ctx.engine.apply_subst(ctx.goal.s, ctx.subst)  # type: ignore[attr-defined]
    if not isinstance(s, Literal) or not s.lang:
        return []
    return _bind_or_test(ctx, ctx.goal.o, Literal(s.lang.lower(), XSD_NS + "string"))


def _valid_for_datatype_value(lit: Literal, dt_iri: str) -> bool:
    if dt_iri in {XSD_NS + "string", RDF_NS + "langString", "http://www.w3.org/2000/01/rdf-schema#Literal"}:
        return True
    if dt_iri in {XSD_NS + "integer", XSD_NS + "int", XSD_NS + "long"}:
        try:
            if not re.match(r"^[+-]?[0-9]+$", lit.lexical):
                return False
            val = int(lit.lexical)
            if dt_iri == XSD_NS + "int":
                return -(2**31) <= val <= 2**31 - 1
            return True
        except Exception:
            return False
    if dt_iri in {XSD_NS + "decimal", XSD_NS + "double", XSD_NS + "float"}:
        try:
            Decimal(lit.lexical)
            return lit.lexical.strip() == lit.lexical
        except Exception:
            return False
    if dt_iri == XSD_NS + "boolean":
        return lit.lexical in {"true", "false", "1", "0"}
    if dt_iri == RDF_NS + "PlainLiteral":
        return bool(re.match(r"^.*@[A-Za-z]*(?:-[A-Za-z0-9]+)*$", lit.lexical))
    return True


def _dt_valid(ctx: BuiltinContext) -> list[Subst]:
    s = ctx.engine.apply_subst(ctx.goal.s, ctx.subst)  # type: ignore[attr-defined]
    o = ctx.engine.apply_subst(ctx.goal.o, ctx.subst)  # type: ignore[attr-defined]
    if isinstance(s, ListTerm) and len(s.elems) == 2:
        lit = ctx.engine.apply_subst(s.elems[0], ctx.subst)  # type: ignore[attr-defined]
        dt = ctx.engine.apply_subst(s.elems[1], ctx.subst)  # type: ignore[attr-defined]
        if isinstance(lit, Literal) and isinstance(dt, Iri):
            return _bind_or_test(ctx, ctx.goal.o, _bool_lit(_valid_for_datatype_value(lit, dt.value)))
    if isinstance(s, Literal) and isinstance(o, Iri):
        return [ctx.subst] if _valid_for_datatype_value(s, o.value) else []
    return []


def _dt_invalid(ctx: BuiltinContext) -> list[Subst]:
    s = ctx.engine.apply_subst(ctx.goal.s, ctx.subst)  # type: ignore[attr-defined]
    o = ctx.engine.apply_subst(ctx.goal.o, ctx.subst)  # type: ignore[attr-defined]
    if isinstance(s, ListTerm) and len(s.elems) == 2:
        lit = ctx.engine.apply_subst(s.elems[0], ctx.subst)  # type: ignore[attr-defined]
        dt = ctx.engine.apply_subst(s.elems[1], ctx.subst)  # type: ignore[attr-defined]
        if isinstance(lit, Literal) and isinstance(dt, Iri):
            return _bind_or_test(ctx, ctx.goal.o, _bool_lit(not _valid_for_datatype_value(lit, dt.value)))
    if isinstance(s, Literal) and isinstance(o, Iri):
        return [ctx.subst] if not _valid_for_datatype_value(s, o.value) else []
    return []


def _dt_same(ctx: BuiltinContext) -> list[Subst]:
    return _math_equal(ctx)


def _dt_different(ctx: BuiltinContext) -> list[Subst]:
    return _math_not_equal(ctx)


def _dt_canonical(ctx: BuiltinContext) -> list[Subst]:
    s = ctx.engine.apply_subst(ctx.goal.s, ctx.subst)  # type: ignore[attr-defined]
    if not isinstance(s, Literal):
        return []
    dt = literal_datatype(s)
    if dt in {XSD_NS + "integer", XSD_NS + "int", XSD_NS + "long"}:
        try:
            out = Literal(str(int(s.lexical)), dt, bare=False)
        except Exception:
            return []
    elif dt == XSD_NS + "boolean":
        b = bool_value(s)
        if b is None:
            return []
        out = _bool_lit(b)
    elif dt == RDF_NS + "PlainLiteral":
        if "@" in s.lexical:
            text, lang = s.lexical.rsplit("@", 1)
            out = Literal(text + "@" + lang.lower(), dt)
        else:
            return []
    else:
        out = Literal(s.lexical, dt, s.lang)
    return _bind_or_test(ctx, ctx.goal.o, out)


# ---------------------------------------------------------------------------
# Additional SWAP-style built-ins used by notation3tests/Eyeling examples.
# ---------------------------------------------------------------------------

def _math_unary_float(fn: Callable[[float], float], inverse: Callable[[float], float] | None = None) -> BuiltinHandler:
    def handler(ctx: BuiltinContext) -> list[Subst]:
        subject = ctx.engine.apply_subst(ctx.goal.s, ctx.subst)  # type: ignore[attr-defined]
        obj = ctx.engine.apply_subst(ctx.goal.o, ctx.subst)  # type: ignore[attr-defined]
        a = _term_num(subject)
        b = _term_num(obj)
        if a is None and b is None:
            return [ctx.subst] if isinstance(subject, Var) and isinstance(obj, Var) else []
        if a is None and b is not None and inverse is not None:
            try:
                datatype = literal_datatype(obj) if isinstance(obj, Literal) else XSD_NS + "double"
                value = Decimal(str(inverse(float(b))))
                if datatype == XSD_NS + "integer" and value != value.to_integral_value():
                    datatype = XSD_NS + "double"
                return _bind_numeric_or_test(ctx, ctx.goal.s, _typed_num_lit(value, datatype, float_style=datatype != XSD_NS + "integer"))
            except Exception:
                return []
        if a is None:
            return []
        try:
            datatype = literal_datatype(subject) if isinstance(subject, Literal) else XSD_NS + "double"
            value = Decimal(str(fn(float(a))))
            if datatype == XSD_NS + "integer" and value != value.to_integral_value():
                datatype = XSD_NS + "double"
            return _bind_numeric_or_test(ctx, ctx.goal.o, _typed_num_lit(value, datatype, float_style=datatype != XSD_NS + "integer"))
        except Exception:
            return []
    return handler


def _math_degrees(ctx: BuiltinContext) -> list[Subst]:
    return _math_unary_float(math.degrees, math.radians)(ctx)


def _list_last(ctx: BuiltinContext) -> list[Subst]:
    elems = _list_elems(ctx, ctx.goal.s)
    if not elems:
        return []
    nxt = _unify_builtin_value(ctx, ctx.goal.o, elems[-1], ctx.subst)
    return [] if nxt is None else [nxt]


def _list_reverse(ctx: BuiltinContext) -> list[Subst]:
    elems = _list_elems(ctx, ctx.goal.s)
    if elems is None:
        return []
    return _bind_or_test(ctx, ctx.goal.o, ListTerm(reversed(elems)))


def _list_map(ctx: BuiltinContext) -> list[Subst]:
    pair = _list_elems(ctx, ctx.goal.s)
    if pair is None or len(pair) != 2:
        return []
    inputs = _list_elems(ctx, pair[0])
    predicate = ctx.engine.apply_subst(pair[1], ctx.subst)  # type: ignore[attr-defined]
    if inputs is None or not isinstance(predicate, Iri):
        return []
    results: list[Term] = []
    for item in inputs:
        value_var = ctx.engine.standardize_term_apart(Var("mapValue"))  # type: ignore[attr-defined]
        if not isinstance(value_var, Var):
            return []
        goal = Triple(ctx.engine.apply_subst(item, ctx.subst), predicate, value_var)  # type: ignore[attr-defined]
        for solution in ctx.engine.solve([goal], dict(ctx.subst)):  # type: ignore[attr-defined]
            value = ctx.engine.apply_subst(value_var, solution)  # type: ignore[attr-defined]
            if not isinstance(value, Var):
                results.append(value)
    return _bind_list_or_test(ctx, ctx.goal.o, results)


def _sort_key(ctx: BuiltinContext, t: Term) -> tuple:
    if isinstance(t, Literal):
        number = numeric_value(t)
        if number is not None and not number.is_nan():
            return (0, number)
        return (1, literal_datatype(t), (t.lang or "").lower(), t.lexical)
    if isinstance(t, ListTerm):
        return (2, tuple(_sort_key(ctx, item) for item in t.elems))
    if isinstance(t, Iri):
        return (3, t.value)
    if isinstance(t, Blank):
        return (4, t.label)
    try:
        return (5, ctx.term_to_n3(t))
    except Exception:
        return (5, repr(t))


def _list_sort(ctx: BuiltinContext) -> list[Subst]:
    elems = _list_elems(ctx, ctx.goal.s)
    if elems is None:
        return []
    return _bind_or_test(ctx, ctx.goal.o, ListTerm(sorted(elems, key=lambda x: _sort_key(ctx, x))))


def _list_member_at(ctx: BuiltinContext) -> list[Subst]:
    pair = _list_elems(ctx, ctx.goal.s)
    if pair is None or len(pair) != 2:
        return []
    elems = _list_elems(ctx, pair[0])
    idx = _term_num(ctx.engine.apply_subst(pair[1], ctx.subst))  # type: ignore[attr-defined]
    if elems is None or idx is None or idx != idx.to_integral_value():
        return []
    i = int(idx)
    if i < 0 or i >= len(elems):
        return []
    nxt = _unify_builtin_value(ctx, ctx.goal.o, elems[i], ctx.subst)
    return [] if nxt is None else [nxt]


def _list_iterate(ctx: BuiltinContext) -> list[Subst]:
    elems = _list_elems(ctx, ctx.goal.s)
    object_value = ctx.engine.apply_subst(ctx.goal.o, ctx.subst)  # type: ignore[attr-defined]
    pair = _list_elems(ctx, object_value)
    if elems is None:
        return []
    results: list[Subst] = []
    if isinstance(object_value, Var):
        for index, item in enumerate(elems):
            nxt = ctx.unify_term(ctx.goal.o, ListTerm((Literal(str(index), XSD_NS + "integer", bare=True), item)), ctx.subst)
            if nxt is not None:
                results.append(nxt)
        return results
    if pair is None or len(pair) != 2:
        return []
    for index, item in enumerate(elems):
        current = ctx.unify_term(pair[0], Literal(str(index), XSD_NS + "integer", bare=True), ctx.subst)
        if current is not None:
            current = _unify_builtin_value(ctx, pair[1], item, current)
        if current is not None:
            results.append(current)
    return results


def _list_remove(ctx: BuiltinContext) -> list[Subst]:
    pair = _list_elems(ctx, ctx.goal.s)
    if pair is None or len(pair) != 2:
        return []
    elems = _list_elems(ctx, pair[0])
    item = ctx.engine.apply_subst(pair[1], ctx.subst)  # type: ignore[attr-defined]
    if elems is None:
        return []
    def same_value(left: Term, right: Term) -> bool:
        if isinstance(left, Literal) and isinstance(right, Literal):
            ln, rn = numeric_value(left), numeric_value(right)
            if ln is not None and rn is not None and literal_datatype(left) == literal_datatype(right):
                return ln == rn
        return ctx.engine.unify_term(left, right, {}) is not None  # type: ignore[attr-defined]
    out = [e for e in elems if not same_value(e, item)]
    return _bind_list_or_test(ctx, ctx.goal.o, out)


def _list_not_member(ctx: BuiltinContext) -> list[Subst]:
    return [] if _list_member(ctx) else [ctx.subst]


def _list_first_rest(ctx: BuiltinContext) -> list[Subst]:
    elems = _list_elems(ctx, ctx.goal.s)
    pair = ctx.engine.apply_subst(ctx.goal.o, ctx.subst)  # type: ignore[attr-defined]
    if not isinstance(pair, ListTerm) or len(pair.elems) != 2:
        return []
    if elems is None:
        rest = pair.elems[1]
        if isinstance(rest, ListTerm):
            return _bind_or_test(ctx, ctx.goal.s, ListTerm((pair.elems[0], *rest.elems)))
        if isinstance(rest, OpenListTerm):
            return _bind_or_test(
                ctx,
                ctx.goal.s,
                OpenListTerm((pair.elems[0], *rest.prefix), rest.tail_var),
            )
        if isinstance(rest, Var):
            return _bind_or_test(ctx, ctx.goal.s, OpenListTerm((pair.elems[0],), rest.name))
        return []
    if not elems:
        return []
    nxt = ctx.unify_term(pair.elems[0], elems[0], ctx.subst)
    if nxt is None:
        return []
    nxt2 = ctx.engine.unify_term(pair.elems[1], ListTerm(elems[1:]), nxt)  # type: ignore[attr-defined]
    return [] if nxt2 is None else [nxt2]


def _string_ci_test(op: Callable[[str, str], bool]) -> BuiltinHandler:
    def handler(ctx: BuiltinContext) -> list[Subst]:
        a = _term_str(ctx.engine.apply_subst(ctx.goal.s, ctx.subst))  # type: ignore[attr-defined]
        b = _term_str(ctx.engine.apply_subst(ctx.goal.o, ctx.subst))  # type: ignore[attr-defined]
        return [ctx.subst] if a is not None and b is not None and op(a.casefold(), b.casefold()) else []
    return handler


def _string_cmp(op: Callable[[str, str], bool]) -> BuiltinHandler:
    def handler(ctx: BuiltinContext) -> list[Subst]:
        a = _term_str(ctx.engine.apply_subst(ctx.goal.s, ctx.subst))  # type: ignore[attr-defined]
        b = _term_str(ctx.engine.apply_subst(ctx.goal.o, ctx.subst))  # type: ignore[attr-defined]
        return [ctx.subst] if a is not None and b is not None and op(a, b) else []
    return handler


def _string_length(ctx: BuiltinContext) -> list[Subst]:
    a = _term_str(ctx.engine.apply_subst(ctx.goal.s, ctx.subst))  # type: ignore[attr-defined]
    if a is None:
        return []
    return _bind_or_test(ctx, ctx.goal.o, Literal(str(len(a)), XSD_NS + "integer", bare=True))


def _string_char_at(ctx: BuiltinContext) -> list[Subst]:
    pair = ctx.engine.apply_subst(ctx.goal.s, ctx.subst)  # type: ignore[attr-defined]
    if not isinstance(pair, ListTerm) or len(pair.elems) != 2:
        return []
    s = _term_str(ctx.engine.apply_subst(pair.elems[0], ctx.subst))  # type: ignore[attr-defined]
    i_num = _term_num(ctx.engine.apply_subst(pair.elems[1], ctx.subst))  # type: ignore[attr-defined]
    if s is None or i_num is None:
        return []
    i = int(i_num)
    if i < 0 or i >= len(s):
        return []
    return _bind_or_test(ctx, ctx.goal.o, Literal(s[i], XSD_NS + "string"))


def _string_set_char_at(ctx: BuiltinContext) -> list[Subst]:
    elems = _list_elems(ctx, ctx.goal.s)
    if elems is None or len(elems) != 3:
        return []
    s = _term_str(ctx.engine.apply_subst(elems[0], ctx.subst))  # type: ignore[attr-defined]
    i_num = _term_num(ctx.engine.apply_subst(elems[1], ctx.subst))  # type: ignore[attr-defined]
    ch = _term_str(ctx.engine.apply_subst(elems[2], ctx.subst))  # type: ignore[attr-defined]
    if s is None or i_num is None or ch is None:
        return []
    i = int(i_num)
    if i < 0 or i >= len(s):
        return []
    return _bind_or_test(ctx, ctx.goal.o, Literal(s[:i] + ch[:1] + s[i + 1 :], XSD_NS + "string"))


def _string_scrape(ctx: BuiltinContext) -> list[Subst]:
    elems = _list_elems(ctx, ctx.goal.s)
    if elems is None or len(elems) < 2:
        return []
    s = _term_str(ctx.engine.apply_subst(elems[0], ctx.subst))  # type: ignore[attr-defined]
    pat = _term_str(ctx.engine.apply_subst(elems[1], ctx.subst))  # type: ignore[attr-defined]
    if s is None or pat is None:
        return []
    m = re.search(pat, s)
    if not m:
        return []
    value = m.group(1) if m.groups() else m.group(0)
    return _bind_or_test(ctx, ctx.goal.o, Literal(value, XSD_NS + "string"))


def _crypto_hash(name: str) -> BuiltinHandler:
    def handler(ctx: BuiltinContext) -> list[Subst]:
        term = ctx.engine.apply_subst(ctx.goal.s, ctx.subst)  # type: ignore[attr-defined]
        if not isinstance(term, Literal):
            return []
        # Match Eyeling's N3 literal representation: hash escaped lexical
        # content, excluding the surrounding quotes.
        s = json.dumps(term.lexical, ensure_ascii=False)[1:-1]
        h = hashlib.new(name)
        h.update(s.encode("utf8"))
        return _bind_or_test(ctx, ctx.goal.o, Literal(h.hexdigest(), XSD_NS + "string"))
    return handler


def _time_part(part: str) -> BuiltinHandler:
    def handler(ctx: BuiltinContext) -> list[Subst]:
        import datetime as _dt
        s = _term_str(ctx.engine.apply_subst(ctx.goal.s, ctx.subst))  # type: ignore[attr-defined]
        if s is None:
            return []
        value = s.replace("Z", "+00:00")
        try:
            d = _dt.datetime.fromisoformat(value)
        except Exception:
            return []
        mapping = {
            "year": d.year,
            "month": d.month,
            "day": d.day,
            "hour": d.hour,
            "minute": d.minute,
            "second": d.second,
        }
        if part == "timeZone":
            tz = s[-6:] if re.search(r"[+-][0-9]{2}:[0-9]{2}$", s) else ("Z" if s.endswith("Z") else "")
            return _bind_or_test(ctx, ctx.goal.o, Literal(tz, XSD_NS + "string"))
        return _bind_or_test(ctx, ctx.goal.o, Literal(str(mapping[part]), XSD_NS + "integer", bare=True))
    return handler


def _time_local(ctx: BuiltinContext) -> list[Subst]:
    import datetime as _dt
    return _bind_or_test(ctx, ctx.goal.o, Literal(_dt.datetime.now(_dt.timezone.utc).isoformat(), XSD_NS + "dateTime"))


def _log_conjunction(ctx: BuiltinContext) -> list[Subst]:
    elems = _list_elems(ctx, ctx.goal.s)
    if elems is None:
        return []
    triples: list[Triple] = []
    seen: set[Triple] = set()
    for e in elems:
        e = ctx.engine.apply_subst(e, ctx.subst)  # type: ignore[attr-defined]
        if not isinstance(e, GraphTerm):
            return []
        for triple in e.triples:
            if triple not in seen:
                seen.add(triple)
                triples.append(triple)
    return _bind_or_test(ctx, ctx.goal.o, GraphTerm(triples))


def _log_collect_all_in(ctx: BuiltinContext) -> list[Subst]:
    parts = _list_elems(ctx, ctx.goal.s)
    if parts is None or len(parts) != 3:
        return []
    blank_vars: dict[str, Var] = {}
    protected_blanks: set[str] = set()

    def remember_bound_blanks(term: Term) -> None:
        if isinstance(term, Blank):
            protected_blanks.add(term.label)
        elif isinstance(term, ListTerm):
            for item in term.elems:
                remember_bound_blanks(item)
        elif isinstance(term, OpenListTerm):
            for item in term.prefix:
                remember_bound_blanks(item)
        elif isinstance(term, GraphTerm):
            for triple in term.triples:
                remember_bound_blanks(triple.s)
                remember_bound_blanks(triple.p)
                remember_bound_blanks(triple.o)

    for bound_value in ctx.subst.values():
        applied_bound = ctx.engine.apply_subst(bound_value, ctx.subst)  # type: ignore[attr-defined]
        remember_bound_blanks(applied_bound)

    def existential(term: Term) -> Term:
        if isinstance(term, Blank):
            if term.label in protected_blanks:
                return term
            return blank_vars.setdefault(term.label, Var(f"_collect_{term.label}"))
        if isinstance(term, ListTerm):
            return ListTerm(existential(item) for item in term.elems)
        if isinstance(term, GraphTerm):
            return GraphTerm(Triple(existential(tr.s), existential(tr.p), existential(tr.o)) for tr in term.triples)
        return term

    value_term, formula, output_term = (existential(part) for part in parts)
    formula = ctx.engine.apply_subst(formula, ctx.subst)  # type: ignore[attr-defined]
    if not isinstance(formula, GraphTerm):
        return []
    values: list[Term] = []
    scope = ctx.engine.apply_subst(ctx.goal.o, ctx.subst)  # type: ignore[attr-defined]
    old_facts = ctx.engine.facts  # type: ignore[attr-defined]
    old_rule_fact_view = ctx.engine._rule_fact_view_active  # type: ignore[attr-defined]
    old_backward_rules = ctx.engine.backward_rules  # type: ignore[attr-defined]
    try:
        if isinstance(scope, GraphTerm):
            ctx.engine.facts = list(scope.triples)  # type: ignore[attr-defined]
            ctx.engine._rule_fact_view_active = False  # type: ignore[attr-defined]
            ctx.engine.backward_rules = []  # type: ignore[attr-defined]
        for solution in ctx.engine.solve(list(formula.triples), dict(ctx.subst)):  # type: ignore[attr-defined]
            value = ctx.engine.apply_subst(value_term, solution)  # type: ignore[attr-defined]
            # collectAllIn is a solution sequence, not a set. Distinct proof
            # solutions may intentionally project the same value.
            if not isinstance(value, Var):
                values.append(value)
    finally:
        ctx.engine.facts = old_facts  # type: ignore[attr-defined]
        ctx.engine._rule_fact_view_active = old_rule_fact_view  # type: ignore[attr-defined]
        ctx.engine.backward_rules = old_backward_rules  # type: ignore[attr-defined]
    return _bind_list_or_test(ctx, output_term, values)


def _log_for_all_in(ctx: BuiltinContext) -> list[Subst]:
    parts = _list_elems(ctx, ctx.goal.s)
    if parts is None or len(parts) != 2:
        return []
    generator = ctx.engine.apply_subst(parts[0], ctx.subst)  # type: ignore[attr-defined]
    condition = ctx.engine.apply_subst(parts[1], ctx.subst)  # type: ignore[attr-defined]
    if not isinstance(generator, GraphTerm) or not isinstance(condition, GraphTerm):
        return []
    scope = ctx.engine.apply_subst(ctx.goal.o, ctx.subst)  # type: ignore[attr-defined]
    old_facts = ctx.engine.facts  # type: ignore[attr-defined]
    old_rule_fact_view = ctx.engine._rule_fact_view_active  # type: ignore[attr-defined]
    old_backward_rules = ctx.engine.backward_rules  # type: ignore[attr-defined]
    try:
        if isinstance(scope, GraphTerm):
            ctx.engine.facts = list(scope.triples)  # type: ignore[attr-defined]
            ctx.engine._rule_fact_view_active = False  # type: ignore[attr-defined]
            ctx.engine.backward_rules = []  # type: ignore[attr-defined]
        for solution in ctx.engine.solve(list(generator.triples), dict(ctx.subst)):  # type: ignore[attr-defined]
            if next(ctx.engine.solve(list(condition.triples), solution), None) is None:  # type: ignore[attr-defined]
                return []
        return [ctx.subst]
    finally:
        ctx.engine.facts = old_facts  # type: ignore[attr-defined]
        ctx.engine._rule_fact_view_active = old_rule_fact_view  # type: ignore[attr-defined]
        ctx.engine.backward_rules = old_backward_rules  # type: ignore[attr-defined]


def _log_parsed_as_n3(ctx: BuiltinContext) -> list[Subst]:
    source = ctx.engine.apply_subst(ctx.goal.s, ctx.subst)  # type: ignore[attr-defined]
    if not isinstance(source, Literal):
        return []
    try:
        formula = _document_to_formula(source.lexical)
        formula = ctx.engine.standardize_term_apart(  # type: ignore[attr-defined]
            formula,
            scope_key="log:parsedAsN3:" + hashlib.sha256(source.lexical.encode()).hexdigest(),
        )
        return _bind_or_test(ctx, ctx.goal.o, formula)
    except Exception:
        return []


def _install_defaults() -> None:
    for local, fn in {
        "equalTo": _math_equal,
        "notEqualTo": _math_not_equal,
        "greaterThan": _math_cmp(lambda a, b: a > b),
        "lessThan": _math_cmp(lambda a, b: a < b),
        "notGreaterThan": _math_cmp(lambda a, b: a <= b),
        "notLessThan": _math_cmp(lambda a, b: a >= b),
        "sum": _math_sum,
        "product": _math_product,
        "difference": _math_difference,
        "quotient": _math_quotient,
        "integerQuotient": _math_integer_quotient,
        "remainder": _math_remainder,
        "exponentiation": _math_exponentiation,
        "negation": _math_negation,
        "absoluteValue": _math_absolute_value,
        "rounded": _math_rounded,
        "sin": _math_unary_float(math.sin, math.asin),
        "cos": _math_unary_float(math.cos, math.acos),
        "tan": _math_unary_float(math.tan, math.atan),
        "sinh": _math_unary_float(math.sinh, math.asinh),
        "cosh": _math_unary_float(math.cosh, math.acosh),
        "tanh": _math_unary_float(math.tanh, math.atanh),
        "asin": _math_unary_float(math.asin, math.sin),
        "acos": _math_unary_float(math.acos, math.cos),
        "atan": _math_unary_float(math.atan, math.tan),
        "degrees": _math_degrees,
    }.items():
        register_builtin(MATH_NS + local, fn)
    for local, fn in {
        "first": _list_first,
        "rest": _list_rest,
        "length": _list_length,
        "memberCount": _list_length,
        "in": _list_in,
        "member": _list_member,
        "append": _list_append,
        "last": _list_last,
        "memberAt": _list_member_at,
        "iterate": _list_iterate,
        "remove": _list_remove,
        "notMember": _list_not_member,
        "reverse": _list_reverse,
        "sort": _list_sort,
        "map": _list_map,
        "firstRest": _list_first_rest,
    }.items():
        register_builtin(LIST_NS + local, fn)
    register_builtin(RDF_FIRST, _list_first)
    register_builtin(RDF_REST, _list_rest)
    for local, fn in {
        "contains": _string_contains,
        "startsWith": _string_starts,
        "endsWith": _string_ends,
        "matches": _string_matches,
        "concatenation": _string_concatenation,
        "concatenate": _string_concatenation,
        "format": _string_format,
        "replace": _string_replace,
        "containsIgnoringCase": _string_ci_test(lambda a, b: b in a),
        "equalIgnoringCase": _string_ci_test(lambda a, b: a == b),
        "notEqualIgnoringCase": _string_ci_test(lambda a, b: a != b),
        "notMatches": _string_not_matches,
        "greaterThan": _string_cmp(lambda a, b: a > b),
        "lessThan": _string_cmp(lambda a, b: a < b),
        "notGreaterThan": _string_cmp(lambda a, b: a <= b),
        "notLessThan": _string_cmp(lambda a, b: a >= b),
        "length": _string_length,
        "charAt": _string_char_at,
        "setCharAt": _string_set_char_at,
        "scrape": _string_scrape,
    }.items():
        register_builtin(STRING_NS + local, fn)
    for local, fn in {
        "uri": _log_uri,
        "dtlit": _log_dtlit,
        "langlit": _log_langlit,
        "rawType": _log_raw_type,
        "includes": _log_includes,
        "notIncludes": _log_not_includes,
        "semantics": _log_semantics,
        "conclusion": _log_conclusion,
        "skolem": _log_skolem,
        "equalTo": _log_equal,
        "notEqualTo": _log_not_equal,
        "conjunction": _log_conjunction,
        "collectAllIn": _log_collect_all_in,
        "forAllIn": _log_for_all_in,
        "parsedAsN3": _log_parsed_as_n3,
        "content": _log_content,
        "semanticsOrError": _log_semantics_or_error,
    }.items():
        register_builtin(LOG_NS + local, fn)
    for local, fn in {
        "sha": _crypto_hash("sha1"),
        "md5": _crypto_hash("md5"),
        "sha256": _crypto_hash("sha256"),
        "sha512": _crypto_hash("sha512"),
    }.items():
        register_builtin(CRYPTO_NS + local, fn)
    for local, fn in {
        "year": _time_part("year"),
        "month": _time_part("month"),
        "day": _time_part("day"),
        "hour": _time_part("hour"),
        "minute": _time_part("minute"),
        "second": _time_part("second"),
        "timeZone": _time_part("timeZone"),
        "localTime": _time_local,
    }.items():
        register_builtin(TIME_NS + local, fn)
    for local, fn in {
        "datatype": _dt_datatype,
        "lexicalForm": _dt_lexical_form,
        "language": _dt_language,
        "validForDatatype": _dt_valid,
        "invalidForDatatype": _dt_invalid,
        "sameValueAs": _dt_same,
        "differentValueFrom": _dt_different,
        "canonicalLiteral": _dt_canonical,
    }.items():
        register_builtin(DT_NS + local, fn)


_install_defaults()
