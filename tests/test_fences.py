"""Behavior tests for the shared fence scanner (fences.find_fences).

These pin the fence semantics the chunker and (later, #157) the parser both
rely on: what opens a fence, what closes it, what is content, and how an
unterminated opener is demoted so headings after it are not hidden.
"""

from __future__ import annotations

import ast
from pathlib import Path

from ragmark.fences import find_fences, unterminated_fence_line

FENCES_SOURCE = Path(__file__).parent.parent / "src" / "ragmark" / "fences.py"


# --- openers and closers ----------------------------------------------------


def test_tilde_fence_is_not_closed_by_backticks() -> None:
    assert find_fences(["```", "~~~", "```"]) == ([(0, 2)], [])


def test_backtick_fence_is_not_closed_by_tildes() -> None:
    assert find_fences(["~~~", "```", "~~~"]) == ([(0, 2)], [])


def test_closer_at_least_as_long_as_opener_closes() -> None:
    assert find_fences(["````", "```", "````"]) == ([(0, 2)], [])


def test_closer_shorter_than_opener_is_content() -> None:
    assert find_fences(["````", "```", "x", "````"]) == ([(0, 3)], [])


def test_closer_with_info_string_is_content() -> None:
    assert find_fences(["```", "```python", "x", "```"]) == ([(0, 3)], [])


def test_backtick_info_string_containing_backtick_is_not_an_opener() -> None:
    assert find_fences(["``` a`b", "x"]) == ([], [])


def test_tilde_info_string_containing_backtick_is_an_opener() -> None:
    assert find_fences(["~~~ a`b", "x", "~~~"]) == ([(0, 2)], [])


def test_three_space_indent_is_a_fence() -> None:
    assert find_fences(["   ```", "x", "```"]) == ([(0, 2)], [])


def test_four_space_indent_is_not_a_fence() -> None:
    assert find_fences(["    ```", "x"]) == ([], [])


def test_tab_before_run_is_not_a_fence() -> None:
    assert find_fences(["\t```", "x"]) == ([], [])


def test_space_then_tab_before_run_is_not_a_fence() -> None:
    assert find_fences([" \t```", "x"]) == ([], [])


def test_indentation_rule_binds_the_closer_three_spaces_closes() -> None:
    assert find_fences(["```", "   ```"]) == ([(0, 1)], [])


def test_indentation_rule_binds_the_closer_four_spaces_is_content() -> None:
    assert find_fences(["```", "    ```", "```"]) == ([(0, 2)], [])


def test_indentation_rule_binds_the_closer_tab_is_content() -> None:
    assert find_fences(["~~~", "\t~~~", "~~~"]) == ([(0, 2)], [])


def test_run_shorter_than_three_backticks_is_not_a_fence() -> None:
    assert find_fences(["``", "x", "``"]) == ([], [])


def test_run_shorter_than_three_tildes_is_not_a_fence() -> None:
    assert find_fences(["~~", "# x", "~~"]) == ([], [])


def test_closer_with_trailing_spaces_closes() -> None:
    assert find_fences(["```", "``` ", "x"]) == ([(0, 1)], [])


def test_closer_with_trailing_tab_closes() -> None:
    assert find_fences(["```", "```\t", "x"]) == ([(0, 1)], [])


def test_closer_followed_by_other_character_is_content() -> None:
    assert find_fences(["```", "```x", "```"]) == ([(0, 2)], [])


def test_closer_followed_by_non_breaking_space_is_content() -> None:
    # U+00A0 is whitespace to str.isspace and to re's \s, but not to the
    # spaces-or-tabs rule, so a closer followed by it is content.
    assert find_fences(["```", "```\u00a0", "```"]) == ([(0, 2)], [])


# --- demote-and-rescan ------------------------------------------------------


def test_unterminated_opener_is_demoted_and_scan_restarts_after_it() -> None:
    assert find_fences(["```", "~~~", "x", "~~~"]) == ([(1, 3)], [0])


def test_repeated_demotion_until_no_opener_is_unclosed() -> None:
    assert find_fences(["```", "x", "~~~", "# H"]) == ([], [0, 2])


# --- unterminated_fence_line ------------------------------------------------


def test_unterminated_fence_line_reports_the_demoted_opener() -> None:
    body = "# A\n\n```\ncode\n\n# B\n\ntext\n\n# C\n\nmore\n"
    assert unterminated_fence_line(body) == 3


def test_unterminated_fence_line_is_none_for_a_balanced_tilde_fence() -> None:
    body = "# A\n\n~~~\n# not heading\n~~~\n\n# B\n\nx\n"
    assert unterminated_fence_line(body) is None


def test_unterminated_fence_line_is_none_for_a_balanced_crlf_tilde_fence() -> None:
    body = "# A\r\n\r\n~~~\r\n# x\r\n~~~\r\n\r\n# B\r\n\r\ny\r\n"
    assert unterminated_fence_line(body) is None


def test_unterminated_fence_line_handles_crlf_like_lf() -> None:
    body = "# A\r\n\r\n```\r\ncode\r\n\r\n# B\r\n"
    assert unterminated_fence_line(body) == 3


def test_unterminated_fence_line_reports_the_lowest_of_two_demoted_openers() -> None:
    body = "# A\n\n```\nx\n~~~\n# H\n"
    assert unterminated_fence_line(body) == 3


# --- import purity ----------------------------------------------------------


def test_fences_module_imports_nothing_from_ragmark() -> None:
    tree = ast.parse(FENCES_SOURCE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(alias.name.split(".")[0] != "ragmark" for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0
            assert (node.module or "").split(".")[0] != "ragmark"
