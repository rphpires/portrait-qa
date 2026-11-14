import string

from portrait_qa.i18n import TEXTS


def fields(text: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def test_languages_have_the_same_keys_and_placeholders():
    pt, en = TEXTS["pt"], TEXTS["en"]
    assert pt.keys() == en.keys()
    assert pt["status"].keys() == en["status"].keys()
    for key in pt:
        if isinstance(pt[key], str):
            assert fields(pt[key]) == fields(en[key]), key


def test_setup_progress_and_error_keys_are_translated():
    from portrait_qa import setup_core

    keys = {
        "saving",
        "installing",
        "installed",
        "updated",
        "stopping",
        "starting",
        "waiting_health",
        "done",
        "port_range",
        "key_required",
        "key_short",
        "no_health",
        "port_busy",
        "firewall_step",
    }
    assert keys <= TEXTS["en"].keys()
    assert setup_core.MIN_KEY_LENGTH == 16
