"""Keeping the account name out of anything shown on screen."""
import os

from vrchronicle import paths


def test_a_path_inside_home_is_abbreviated():
    home = os.path.normpath(os.path.expanduser("~"))
    got = paths.pretty(os.path.join(home, "Pictures", "VRChat"))
    assert got == os.path.join("%USERPROFILE%", "Pictures", "VRChat")
    assert home not in got


def test_home_itself_has_no_trailing_separator():
    assert paths.pretty(os.path.expanduser("~")) == "%USERPROFILE%"


def test_a_sibling_that_merely_shares_the_prefix_is_left_alone():
    """C:\\Users\\Erikson is not inside C:\\Users\\Erik."""
    home = os.path.normpath(os.path.expanduser("~"))
    sibling = home + "son"
    assert paths.pretty(sibling) == sibling


def test_an_unrelated_path_is_returned_unchanged():
    assert paths.pretty("D:\\Photos") == os.path.normpath("D:\\Photos")
    assert paths.pretty("") == ""
