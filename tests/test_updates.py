"""Which published release counts as newer than the running build."""
from vrchronicle import paths
from vrchronicle.updates import is_newer


def test_a_higher_release_is_newer():
    assert is_newer("v1.2.1", "1.2.0")
    assert is_newer("v1.3.0", "1.2.9")
    assert is_newer("v2.0.0", "1.9.9")
    assert is_newer("v1.10.0", "1.9.0")      # 10 beats 9, not "1 then 0"


def test_the_same_release_is_not_newer():
    assert not is_newer("v1.2.0", "1.2.0")
    assert not is_newer("1.2.0", "1.2.0")
    assert not is_newer("v1.2.0.0", "1.2.0")


def test_a_release_candidate_is_not_newer_than_the_real_release():
    """The whole point: an -rc tag must never nag a user running the release."""
    assert not is_newer("v1.2.0-rc1", "1.2.0")
    assert not is_newer("v1.2.0-beta.2", "1.2.0")
    assert not is_newer("v1.2.0+build20260822", "1.2.0")
    assert is_newer("v1.3.0", "1.3.0-rc1")   # but the release beats its own rc


def test_nonsense_tags_never_look_newer():
    assert not is_newer("nightly", paths.APP_VERSION)
    assert not is_newer("", paths.APP_VERSION)
    assert not is_newer("v1.2", "1.2.0")


def test_the_package_and_the_app_agree_on_the_version():
    import vrchronicle
    assert vrchronicle.__version__ == paths.APP_VERSION
