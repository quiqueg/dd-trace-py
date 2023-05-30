#!/usr/bin/env python3
# -*- encoding: utf-8 -*-
import pytest

try:
    from tests.appsec.iast.aspects.conftest import _iast_patched_module
    from ddtrace.appsec.iast._taint_tracking import get_tainted_ranges
    from ddtrace.appsec.iast._taint_tracking import taint_pyobject
    from ddtrace.appsec.iast._taint_tracking import Source
    from ddtrace.appsec.iast._taint_tracking import OriginType
except (ImportError, AttributeError):
    pytest.skip("IAST not supported for this Python version", allow_module_level=True)

mod = _iast_patched_module("tests.appsec.iast.fixtures.aspects.str_methods")


class TestOperatorJoinReplacement(object):
    def test_string_join_tainted_joiner(self, context):  # type: () -> None
        # taint "joi" from "-joiner-"
        string_input = taint_pyobject(
            "-joiner-", Source("test_add_aspect_tainting_left_hand", "foo", OriginType.PARAMETER), 1, 3
        )
        it = ["a", "b", "c"]

        result = mod.do_join(string_input, it)
        assert not get_tainted_ranges(result)

    def test_string_join_tainted_joined(self, context):  # type: () -> None
        string_input = "-joiner-"
        it = [
            create_taint_range_with_format(":+-aaa-+:a"),
            "bbbb",
            create_taint_range_with_format(":+-ccc-+:c"),
        ]

        result_join = mod.do_join(string_input, it)
        assert as_formatted_evidence(result_join) == ":+-aaa-+:a-joiner-bbbb-joiner-:+-ccc-+:c"

    def test_string_join_tainted_all(self, context):  # type: () -> None
        string_input = ":+--jo-+:iner-"
        it = [
            ":+-a-+:aaa",
            "bbbb",
            ":+-cccc-+:",
            ":+-ddd-+:d",
            ":+-ee-+:ee",
            ":+-fff-+:f",
            ":+-gggg-+:",
        ]
        result_join = mod.do_join(string_input, it)
        assert (
            as_formatted_evidence(result_join)
            == ":+-a-+:aaa:+--jo-+:iner-bbbb:+--jo-+:iner-:+-cccc-+::+--jo-+:iner-:+-ddd-+:d"
            ":+--jo-+:iner-:+-ee-+:ee:+--jo-+:iner-:+-fff-+:f:+--jo-+:iner-:+-gggg-+:"
        )

    def test_string_join_generator(self, context):  # type: () -> None
        # Not tainted
        base_string = "abcde"
        result = mod.get_generator_string(base_string)
        assert as_formatted_evidence(result) == "AbcdeAbcdeAbcde"

        # Tainted
        tainted_base_string = create_taint_range_with_format(":+-abc-+:de")
        result = mod.get_generator_string(tainted_base_string)
        assert as_formatted_evidence(result) == ":+-Abc-+:de:+-Abc-+:de:+-Abc-+:de"

    def test_string_join_yield(self, context):  # type: () -> None
        # Not tainted
        base_string = "abcde"
        result = mod.get_generator_string_2(base_string)
        assert as_formatted_evidence(result) == "xabcdeyabcdez"

        # Tainted
        tainted_base_string = create_taint_range_with_format(":+-abc-+:de")
        result = mod.get_generator_string_2(tainted_base_string)
        assert as_formatted_evidence(result) == "x:+-abc-+:dey:+-abc-+:dez"
