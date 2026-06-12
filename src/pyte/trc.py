# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Konstantin Ushakov
"""Read-only access to TRC (expected results) databases via TE lib/trc.

All matching semantics (wildcards, tag logic expressions, result
selection) come from the C library through the shim and are never
reimplemented here.

Iteration matching (``Db.match``): with the default flags=0 the C
walker (``trc_db_walker_step_iter``) returns the LAST matching
``<iter>`` record in document order, whether that record is exact or
wildcard.  "Exact beats wildcard" priority only applies when
``STEP_ITER_NO_MATCH_*`` flags are used to exclude categories.

Memory notes:
    Group, Iter, Test and Entry hold borrowed C pointers owned by the Db
    handle.  They are valid only while the Db is open; accessing them
    after ``Db.close()`` (or after the ``with`` block exits) is
    undefined behaviour.
"""
from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping, Sequence
from os import PathLike

from pyte.errors import TrcError, check

# Public re-export so callers can do ``from pyte.trc import TrcError``.
__all__ = [
    "TrcError",
    "Db",
    "Test",
    "Iter",
    "Group",
    "Entry",
    "parse_tag_expr",
    "quiet_logging",
    "tag_expr_matches",
    "status_name",
    "status_value",
]

TEST_TYPES = {0: "unknown", 1: "script", 2: "session", 3: "package"}

_STATUS_BY_VALUE: dict[int, str] = {}
_STATUS_BY_NAME: dict[str, int] = {}


def _statuses() -> dict[int, str]:
    global _STATUS_BY_VALUE, _STATUS_BY_NAME
    if not _STATUS_BY_VALUE:
        from pyte._shim import lib
        _STATUS_BY_VALUE = {
            lib.PYTE_TE_TEST_INCOMPLETE: "INCOMPLETE",
            lib.PYTE_TE_TEST_UNSPEC: "UNSPEC",
            lib.PYTE_TE_TEST_EMPTY: "EMPTY",
            lib.PYTE_TE_TEST_SKIPPED: "SKIPPED",
            lib.PYTE_TE_TEST_FAKED: "FAKED",
            lib.PYTE_TE_TEST_PASSED: "PASSED",
            lib.PYTE_TE_TEST_FAILED: "FAILED",
        }
        _STATUS_BY_NAME.update(
            {v: k for k, v in _STATUS_BY_VALUE.items()})
    return _STATUS_BY_VALUE


def status_name(value: int) -> str:
    """Return the string name for a TE test status integer."""
    return _statuses().get(value, f"UNKNOWN({value})")


def status_value(name: str) -> int:
    """Return the integer value for a TE test status name string."""
    _statuses()
    try:
        return _STATUS_BY_NAME[name.upper()]
    except KeyError:
        raise TrcError(f"unknown test status name: {name!r}")


def _dec(cdata) -> str | None:
    """Decode a const char* to str, returning None for NULL."""
    from pyte._shim import ffi
    if cdata == ffi.NULL:
        return None
    return ffi.string(cdata).decode("utf-8", "backslashreplace")


class _TagSet:
    """tqh_strings holder for a set of run tags (context manager)."""

    def __init__(self, tags: Iterable[str]):
        from pyte._shim import lib
        self._h = lib.pyte_tq_strings_new()
        for tag in tags:
            check(lib.pyte_tq_strings_add(self._h, tag.encode()),
                  f"tq_strings_add({tag})", TrcError)

    def __enter__(self):
        return self._h

    def __exit__(self, *exc):
        from pyte._shim import lib
        lib.pyte_tq_strings_free(self._h)


class Entry:
    """A single result entry (status + optional verdicts) in a Group.

    Holds a borrowed pointer valid only while the owning Db is open.
    """

    def __init__(self, handle):
        self._h = handle

    @property
    def status(self) -> str:
        """Test status string (e.g. "PASSED", "FAILED")."""
        from pyte._shim import lib
        return status_name(lib.pyte_trc_entry_status(self._h))

    @property
    def key(self) -> str | None:
        """Bug/ticket key associated with this entry, or None."""
        from pyte._shim import lib
        return _dec(lib.pyte_trc_entry_key(self._h))

    @property
    def notes(self) -> str | None:
        """Free-form notes, or None."""
        from pyte._shim import lib
        return _dec(lib.pyte_trc_entry_notes(self._h))

    @property
    def verdicts(self) -> list[str]:
        """Ordered list of verdict strings for this entry."""
        from pyte._shim import lib
        result = []
        v = lib.pyte_trc_entry_first_verdict(self._h)
        while v:
            result.append(_dec(lib.pyte_trc_verdict_str(v)))
            v = lib.pyte_trc_verdict_next(v)
        return result


class Group:
    """An expected-results group (tag expression + one or more entries).

    Holds a borrowed pointer valid only while the owning Db is open.
    """

    def __init__(self, handle):
        self._h = handle

    def __eq__(self, other) -> bool:
        if not isinstance(other, Group):
            return NotImplemented
        return self._h == other._h

    def __hash__(self) -> int:
        return hash(self._h)

    @property
    def tags_str(self) -> str | None:
        """Raw tag expression string (e.g. "linux&jumbo"), or None."""
        from pyte._shim import lib
        return _dec(lib.pyte_trc_result_tags(self._h))

    @property
    def key(self) -> str | None:
        """Bug/ticket key for this group, or None."""
        from pyte._shim import lib
        return _dec(lib.pyte_trc_result_key(self._h))

    @property
    def notes(self) -> str | None:
        """Free-form notes, or None."""
        from pyte._shim import lib
        return _dec(lib.pyte_trc_result_notes(self._h))

    def entries(self) -> list[Entry]:
        """All result entries in this group."""
        from pyte._shim import lib
        result = []
        e = lib.pyte_trc_result_first_entry(self._h)
        while e:
            result.append(Entry(e))
            e = lib.pyte_trc_entry_next(e)
        return result

    def matches(self, status: str,
                verdicts: Sequence[str] = ()) -> Entry | None:
        """Return the matching Entry if the obtained result is expected.

        Builds a transient te_test_result from *status* and *verdicts*,
        calls ``trc_is_result_expected``, and returns the matching
        Entry or None.
        """
        from pyte._shim import ffi, lib
        result = lib.pyte_test_result_new(status_value(status))
        try:
            for v in verdicts:
                check(lib.pyte_test_result_add_verdict(result, v.encode()),
                      f"add_verdict({v!r})", TrcError)
            entry_h = lib.trc_is_result_expected(self._h, result)
            if entry_h == ffi.NULL:
                return None
            return Entry(entry_h)
        finally:
            lib.pyte_test_result_free(result)


class Iter:
    """A single iteration record from the TRC database.

    Holds a borrowed pointer valid only while the owning Db is open.
    """

    def __init__(self, db: "Db", handle):
        self._db = db
        self._h = handle

    @property
    def args(self) -> list[tuple[str, str]]:
        """Ordered list of (name, value) argument pairs.

        An empty-string value means the argument is a wildcard.
        """
        from pyte._shim import lib
        result = []
        a = lib.pyte_trc_iter_first_arg(self._h)
        while a:
            name = _dec(lib.pyte_trc_arg_name(a)) or ""
            value = _dec(lib.pyte_trc_arg_value(a))
            if value is None:
                value = ""
            result.append((name, value))
            a = lib.pyte_trc_arg_next(a)
        return result

    def args_dict(self) -> dict[str, str]:
        """Arguments as a dict; wildcard values are empty strings."""
        return dict(self.args)

    @property
    def wildcard_args(self) -> list[str]:
        """Names of arguments whose value is the empty-string wildcard."""
        return [name for name, value in self.args if value == ""]

    @property
    def notes(self) -> str | None:
        """Free-form iteration notes, or None."""
        from pyte._shim import lib
        return _dec(lib.pyte_trc_iter_notes(self._h))

    @property
    def filename(self) -> str | None:
        """Source XML filename, or None."""
        from pyte._shim import lib
        return _dec(lib.pyte_trc_iter_filename(self._h))

    @property
    def file_pos(self) -> int:
        """Line number in the source XML file."""
        from pyte._shim import lib
        return lib.pyte_trc_iter_file_pos(self._h)

    def default(self) -> Group | None:
        """The default result group (no tag expression), or None."""
        from pyte._shim import ffi, lib
        h = lib.pyte_trc_iter_default_result(self._h)
        if h == ffi.NULL:
            return None
        return Group(h)

    def groups(self) -> list[Group]:
        """All tagged result groups for this iteration."""
        from pyte._shim import lib
        result = []
        g = lib.pyte_trc_iter_first_result(self._h)
        while g:
            result.append(Group(g))
            g = lib.pyte_trc_result_next(g)
        return result

    def exp_result(self, tags: Iterable[str]) -> Group | None:
        """Return the expected-result group for the given run tags.

        Delegates fully to the C library's tag-matching logic.
        """
        from pyte._shim import ffi, lib
        with _TagSet(tags) as tag_h:
            h = lib.trc_db_iter_get_exp_result(
                self._h, tag_h, self._db.last_match)
        if h == ffi.NULL:
            return None
        return Group(h)

    def child_tests(self) -> Iterator["Test"]:
        """Iterate over child tests of this iteration (for package iters)."""
        from pyte._shim import ffi, lib
        t = lib.pyte_trc_iter_first_test(self._h)
        while t != ffi.NULL:
            yield Test(self._db, t)
            t = lib.pyte_trc_test_next(t)


class Test:
    """A test or package node in the TRC database.

    Holds a borrowed pointer valid only while the owning Db is open.
    """

    def __init__(self, db: "Db", handle):
        self._db = db
        self._h = handle

    @property
    def name(self) -> str:
        """Short test name (last path component)."""
        from pyte._shim import lib
        return _dec(lib.pyte_trc_test_name(self._h)) or ""

    @property
    def path(self) -> str:
        """Full slash-separated path from the DB root."""
        from pyte._shim import lib
        return _dec(lib.pyte_trc_test_path(self._h)) or ""

    @property
    def test_type(self) -> str:
        """Type string: "unknown", "script", "session", or "package"."""
        from pyte._shim import lib
        return TEST_TYPES.get(lib.pyte_trc_test_type(self._h), "unknown")

    @property
    def aux(self) -> bool:
        """True if this is an auxiliary test entry."""
        from pyte._shim import lib
        return bool(lib.pyte_trc_test_aux(self._h))

    @property
    def objective(self) -> str | None:
        """Test objective string, or None."""
        from pyte._shim import lib
        return _dec(lib.pyte_trc_test_objective(self._h))

    @property
    def notes(self) -> str | None:
        """Free-form notes, or None."""
        from pyte._shim import lib
        return _dec(lib.pyte_trc_test_notes(self._h))

    @property
    def filename(self) -> str | None:
        """Source XML filename, or None."""
        from pyte._shim import lib
        return _dec(lib.pyte_trc_test_filename(self._h))

    @property
    def file_pos(self) -> int:
        """Line number in the source XML file."""
        from pyte._shim import lib
        return lib.pyte_trc_test_file_pos(self._h)

    def iters(self) -> Iterator[Iter]:
        """Iterate over all iteration records for this test."""
        from pyte._shim import ffi, lib
        it = lib.pyte_trc_test_first_iter(self._h)
        while it != ffi.NULL:
            yield Iter(self._db, it)
            it = lib.pyte_trc_iter_next(it)


class Db:
    """An open TRC database.

    Use as a context manager (``with Db.open(path) as db:``) to ensure
    ``close()`` is called even on error.
    """

    def __init__(self, handle):
        self._h = handle

    @classmethod
    def open(cls, path: str | PathLike) -> "Db":
        """Open a TRC XML database, applying XInclude if needed."""
        from pyte._shim import ffi, lib
        out = ffi.new("te_trc_db **")
        check(lib.pyte_trc_db_open(str(path).encode(), out),
              f"trc_db_open({path})", TrcError)
        return cls(out[0])

    def close(self) -> None:
        """Close the database; idempotent."""
        if self._h is not None:
            from pyte._shim import lib
            lib.trc_db_close(self._h)
            self._h = None

    def __enter__(self) -> "Db":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    @property
    def last_match(self) -> bool:
        """Whether the last walker match was a 'last match' (new record)."""
        from pyte._shim import lib
        return bool(lib.pyte_trc_db_last_match(self._h))

    def tests(self) -> Iterator[Test]:
        """Iterate over top-level test nodes in the database."""
        from pyte._shim import ffi, lib
        t = lib.pyte_trc_db_first_test(self._h)
        while t != ffi.NULL:
            yield Test(self, t)
            t = lib.pyte_trc_test_next(t)

    def walk_tests(self) -> Iterator[Test]:
        """Depth-first iteration over all Test nodes in the database.

        For each iteration of every package/session, child tests are
        recursively visited before moving to siblings.
        """
        def _recurse(test: Test) -> Iterator[Test]:
            yield test
            for it in test.iters():
                for child in it.child_tests():
                    yield from _recurse(child)

        for top in self.tests():
            yield from _recurse(top)

    def find_tests(self, query: str) -> list[Test]:
        """Find test nodes whose path matches *query*.

        Matching is done on path-component boundaries: the stored path
        and query are both normalized to start with "/" and then an
        exact match is tried first, followed by an endswith("/"+query)
        check.  This prevents partial-component false positives (e.g.
        "cho" would not match "demo/echo").
        """
        norm_query = "/" + query.lstrip("/")
        results = []
        for t in self.walk_tests():
            p = "/" + t.path.lstrip("/")
            if p == norm_query or p.endswith("/" + norm_query.lstrip("/")):
                results.append(t)
        return results

    def match(self, test: Test, args: Mapping[str, str],
              allow_wild: bool = True) -> Iter | None:
        """Find the iteration record matching the given arguments.

        Delegates to the canonical lib/trc walker with flags=0
        (allow_wild=True) or PYTE_STEP_ITER_NO_MATCH_WILD
        (allow_wild=False).

        With allow_wild=True the walker returns the LAST matching
        ``<iter>`` record in document order — exact or wildcard.
        With allow_wild=False only exact (non-wildcard) records are
        considered, and None is returned if no exact record matches.
        """
        from pyte._shim import ffi, lib
        walker = lib.trc_db_new_walker(self._h)
        try:
            lib.trc_db_walker_go_to_test(walker, test._h)
            arr = ffi.new("trc_report_argument[]", len(args))
            keep = []
            for i, (name, value) in enumerate(args.items()):
                cname = ffi.new("char[]", name.encode())
                cvalue = ffi.new("char[]", str(value).encode())
                keep += [cname, cvalue]
                arr[i].name = cname
                arr[i].value = cvalue
                arr[i].variable = False
            flags = 0 if allow_wild else lib.PYTE_STEP_ITER_NO_MATCH_WILD
            if not lib.pyte_trc_walker_step_iter(
                    walker, len(args), arr, flags):
                return None
            return Iter(self, lib.pyte_trc_walker_iter(walker))
        finally:
            lib.trc_db_free_walker(walker)


def _logic_expr_reset() -> None:
    """Work around a bison/flex global-state bug in logic_expr_parse.

    The C library's logic_expr_parse() uses a non-reentrant bison/flex
    scanner with global state.  When a parse fails the scanner's
    internal buffer is left in an inconsistent state; a subsequent
    trc_db_open() call that parses tag expressions from XML will also
    fail silently (returning NULL for result keys).

    Performing a second parse call — even one that also fails — drains
    the remaining error-recovery lookahead and leaves the scanner in a
    clean state.  This function performs that cleanup call; it is called
    unconditionally after any failed logic_expr_parse.
    """
    from pyte._shim import ffi, lib
    out = ffi.new("logic_expr **")
    lib.logic_expr_parse(b"_reset_", out)


def _parse_logic_expr(expr: str):
    """Parse and return logic_expr* (caller frees with logic_expr_free).

    Drains the scanner state on failure — the ONLY sanctioned
    logic_expr_parse call site; see _logic_expr_reset().
    """
    from pyte._shim import ffi, lib
    out = ffi.new("logic_expr **")
    if lib.logic_expr_parse(expr.encode(), out) != 0:
        _logic_expr_reset()
        raise TrcError(f"invalid tag expression: {expr!r}")
    return out[0]


def parse_tag_expr(expr: str) -> None:
    """Parse a TRC tag expression string, raising TrcError on failure.

    The parsed expression is freed immediately; this function is only
    useful to validate that *expr* is syntactically correct.
    """
    from pyte._shim import lib
    lib.logic_expr_free(_parse_logic_expr(expr))


def quiet_logging() -> None:
    """Install a no-op TE logging backend (for CLI use).

    Suppresses lib/trc warnings like "Duplicated iteration" that
    otherwise go through an unset/IPC logging backend.
    """
    from pyte._shim import lib
    lib.pyte_trc_quiet_logging()


def tag_expr_matches(expr: str | None, tags: Iterable[str]) -> bool:
    """Return True if *tags* satisfy the TRC tag expression *expr*.

    A None or empty *expr* matches anything (TRC convention: a result
    group with no tags attribute applies to all tag sets).
    """
    if not expr:
        return True
    from pyte._shim import lib
    parsed = _parse_logic_expr(expr)
    try:
        with _TagSet(tags) as tag_h:
            result = lib.logic_expr_match(parsed, tag_h)
        return result >= 0
    finally:
        lib.logic_expr_free(parsed)
