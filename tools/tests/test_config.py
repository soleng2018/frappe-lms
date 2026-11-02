"""Unit tests for nile_tools.config. No network, no real .env: everything runs in tmp_path."""

import logging
import re
import subprocess
import sys

import pytest

from nile_tools import cli, config

NAMES = [k.name for k in config.env_keys()]


def parse(text):
    return config.parse_env(text, NAMES)


# --- strict parser (AC-5) ---


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("LMS_HOSTNAME='a'\n", "character outside"),
        ('LMS_HOSTNAME="a"\n', "character outside"),
        ("LMS_HOSTNAME=a b\n", "character outside"),
        ("LMS_HOSTNAME=a$b\n", "character outside"),
        ("LMS_HOSTNAME=a#b\n", "character outside"),
        ("LMS_HOSTNAME=a\\b\n", "character outside"),
        ("export LMS_HOSTNAME=a\n", "'export' is not allowed"),
        ("LMS_HOSTNAME\n", "no '='"),
        ("lms_hostname=a\n", "bad key name"),
        ("LMS_HOSTNAME=a\nLMS_HOSTNAME=b\n", "appears twice (first on line 1)"),
        ("LMS_HOSTNAME=a\r\n", "CRLF"),
        ("﻿LMS_HOSTNAME=a\n", "byte order mark"),
        ("LMS_HOSTNAME=a \n", "trailing spaces"),
        ("LMS_HOSTNME=a\n", "unknown key LMS_HOSTNME"),
        (" LMS_HOSTNAME=a\n", "bad key name"),
    ],
)
def test_parser_rejects_each_bad_line_with_its_line_number(text, message):
    errors = parse(text).errors
    assert any(message in e for e in errors), errors
    assert all(e.startswith("line ") for e in errors)


def test_parser_reports_the_line_number_of_the_bad_line():
    errors = parse("# c\n\nLMS_HOSTNAME=ok\nDB_ROOT_PASSWORD='x'\n").errors
    expected = (
        "line 4: DB_ROOT_PASSWORD has a character outside A-Za-z0-9_.:/@+=,- "
        "(no quotes, spaces, $, # or backslash)"
    )
    assert errors == (expected,)


def test_parser_accepts_equals_and_underscore_and_compose_extras():
    env = parse("LMS_ENCRYPTION_KEY=ab_c-d==\nCOMPOSE_PROFILES=tools\n# note\n\n")
    assert not env.errors
    assert env.values["LMS_ENCRYPTION_KEY"] == "ab_c-d=="
    assert env.lines["COMPOSE_PROFILES"] == 2


def test_parser_never_puts_the_bad_value_in_an_error():
    errors = parse("DB_ROOT_PASSWORD=top secret value\n").errors
    assert "secret value" not in " ".join(errors)


def test_parser_accepts_a_file_without_a_final_newline():
    assert parse("LMS_HOSTNAME=a").values == {"LMS_HOSTNAME": "a"}


# --- validators and scopes (AC-4, AC-5) ---


def test_check_values_names_every_bad_key_at_once_without_values():
    env = parse("LMS_HOSTNAME=a_b\nLMS_API_KEY=zz\nAUTHENTIK_STUDENT_GROUP_SUFFIX=Ad1\n")
    problems = config.check_values(env, config.env_keys(), "up")
    text = "\n".join(problems)
    for name in ("LMS_HOSTNAME", "LMS_API_KEY", "AUTHENTIK_STUDENT_GROUP_SUFFIX"):
        assert name in text
    assert "line 1: LMS_HOSTNAME" in text
    assert "zz" not in text.replace("hex", "")


def test_missing_required_key_is_reported_but_optional_scope_key_is_not_for_up():
    problems = config.check_values(parse(""), config.env_keys(), "up")
    assert any(p.startswith("AUTHENTIK_HOSTNAME is missing") for p in problems)
    assert not any("AUTHENTIK_API_TOKEN" in p for p in problems)


def test_authentik_scope_also_requires_the_token():
    problems = config.check_values(parse(""), config.env_keys(), "tools-authentik")
    assert any(p.startswith("AUTHENTIK_API_TOKEN is missing") for p in problems)


@pytest.mark.parametrize(
    ("validator", "good", "bad"),
    [
        ("hostname", "guide.nile.global", "-bad.example.com"),
        ("hostname", "localhost", "a..b"),
        ("hostname", "a" * 63 + ".com", "a" * 64 + ".com"),
        ("email", "nile-tools@example.com", "nile-tools"),
        ("hex32", "0" * 32, "0" * 31),
        ("hex32", "abcdef0123456789abcdef0123456789", "ABCDEF0123456789abcdef0123456789"),
        ("letters", "NileWorkshop", "Nile1"),
        ("letters", "Admin", "Admin-x"),
    ],
)
def test_validators(validator, good, bad):
    check = config.VALIDATORS[validator]
    assert check(good) is None
    assert check(bad) is not None


def test_fernet_validator_wants_44_chars_decoding_to_32_bytes():
    check = config.VALIDATORS["fernet"]
    assert check(config.generate_value(_key("LMS_ENCRYPTION_KEY"))) is None
    assert check("a" * 44) is not None
    assert check("a" * 43) is not None


def _key(name):
    return next(k for k in config.KEYS if k.name == name)


# --- key list invariants and generators (AC-1, AC-3) ---


def test_key_names_are_unique_and_use_an_area_prefix():
    names = [k.name for k in config.KEYS]
    assert len(names) == len(set(names))
    assert all(re.match(r"^[A-Z][A-Z0-9_]*$", n) for n in names)


def test_a_secret_key_never_carries_a_default_and_is_never_committed():
    for key in config.KEYS:
        if key.secret:
            assert key.default == "", key.name
            assert key.source in ("generated", "operator"), key.name


def test_every_generated_key_has_a_generator_that_passes_its_validator():
    for key in config.KEYS:
        if key.source == "generated":
            value = config.generate_value(key)
            assert re.match(r"^[A-Za-z0-9_.:/@+=,-]+$", value), key.name
            assert key.validator is None or config.VALIDATORS[key.validator](value) is None


def test_every_default_passes_its_own_validator():
    for key in config.KEYS:
        if key.default and key.validator:
            assert config.VALIDATORS[key.validator](key.default) is None, key.name


def test_password_never_starts_with_a_symbol(monkeypatch):
    draws = iter(["-bad", "_bad", "good-one"])
    monkeypatch.setattr(config.secrets, "token_urlsafe", lambda n: next(draws))
    assert config._password() == "good-one"


def test_generating_for_a_key_without_a_generator_is_an_error():
    with pytest.raises(config.ConfigError, match="LMS_HOSTNAME"):
        config.generate_value(_key("LMS_HOSTNAME"))


def test_committed_and_env_keys_partition_the_list():
    both = {k.name for k in config.env_keys()} | {k.name for k in config.committed_keys()}
    assert both == {k.name for k in config.KEYS}
    assert not {k.name for k in config.env_keys()} & {k.name for k in config.committed_keys()}


# --- sample (AC-1) ---


def test_sample_lists_every_env_key_exactly_once_with_secrets_blank():
    sample = parse(config.render_sample())
    assert not sample.errors
    assert list(sample.values) == NAMES
    for key in config.env_keys():
        if key.secret:
            assert sample.values[key.name] == ""
        else:
            assert sample.values[key.name] == key.default


def test_sample_has_a_comment_per_key_and_a_heading_per_group():
    lines = config.render_sample().splitlines()
    for key in config.env_keys():
        at = lines.index(f"{key.name}={key.default}")
        assert lines[at - 1].startswith("# ") and key.description in lines[at - 1]
    for group in {k.group for k in config.env_keys()}:
        assert f"# == {group} ==" in lines


def test_sample_marks_frozen_keys_and_explains_first_run_steps():
    sample = config.render_sample()
    assert "make init" in sample and "private copy" in sample
    assert "(fixed)" in sample


def test_the_committed_sample_is_the_generated_one(request):
    repo = request.config.rootpath.parent
    assert (repo / ".env.sample").read_text() == config.render_sample()


# --- init pieces (AC-3) ---


def test_add_missing_inserts_under_the_group_heading_and_keeps_order():
    text = config.render_sample()
    removed = text.replace("LMS_API_SECRET=\n", "").replace("# Service user API secret", "# x")
    out = config.add_missing(removed, parse(removed).values)
    assert out.index("LMS_API_SECRET=") < out.index("# == DB ==")
    assert out.index("LMS_API_SECRET=") > out.index("LMS_API_KEY=")


def test_add_missing_creates_a_heading_for_a_new_group():
    out = config.add_missing("LMS_HOSTNAME=a\n", {"LMS_HOSTNAME"})
    assert "# == DB ==\n# MariaDB root password" in out
    assert out.endswith("TRAEFIK_CERT_RESOLVER=letsencrypt\n")


def test_add_missing_changes_nothing_when_every_key_is_there():
    text = config.render_sample()
    assert config.add_missing(text, set(NAMES)) == text


def test_fill_generated_fills_only_blank_generated_keys():
    out = config.fill_generated("LMS_API_KEY=\nDB_ROOT_PASSWORD=mine\nLMS_HOSTNAME=\n")
    values = parse(out).values
    assert len(values["LMS_API_KEY"]) == 32
    assert values["DB_ROOT_PASSWORD"] == "mine"
    assert values["LMS_HOSTNAME"] == ""


# --- masking (AC-7) ---


def test_show_masks_a_set_secret_and_marks_a_blank_one():
    shown = config.render_show({"DB_ROOT_PASSWORD": "hunter2hunter2", "LMS_HOSTNAME": "a.b"})
    assert "DB_ROOT_PASSWORD=*****" in shown
    assert "AUTHENTIK_API_TOKEN=(blank)" in shown
    assert "LMS_HOSTNAME=a.b" in shown
    assert "hunter2" not in shown


def test_show_masks_an_unknown_key_it_cannot_classify():
    assert "COMPOSE_X=*****" in config.render_show({"COMPOSE_X": "v"})


def test_scrub_replaces_long_secrets_and_leaves_short_ones():
    assert config.scrub("a hunter2hunter2 b", ["hunter2hunter2"]) == "a ***** b"
    assert config.scrub("a abc b", ["abc"]) == "a abc b"


def test_masking_scrubs_log_records_and_uncaught_exceptions(capsys):
    factory, hook = logging.getLogRecordFactory(), sys.excepthook
    try:
        config.install_masking(["topsecretvalue1"])
        record = logging.getLogger("t").makeRecord(
            "t", 20, "f", 1, "pw %s", ("topsecretvalue1",), None
        )
        assert record.getMessage() == "pw *****"
        try:
            raise RuntimeError("bad topsecretvalue1")
        except RuntimeError:
            sys.excepthook(*sys.exc_info())
        assert "topsecretvalue1" not in capsys.readouterr().err
    finally:
        logging.setLogRecordFactory(factory)
        sys.excepthook = hook


# --- loading (precedence, files) ---


def test_process_environment_wins_over_the_file_for_known_keys(tmp_path):
    (tmp_path / ".env").write_text("LMS_HOSTNAME=file.example.com\n")
    env = config.load_env(tmp_path, {"LMS_HOSTNAME": "env.example.com", "OTHER": "x"})
    assert env.values == {"LMS_HOSTNAME": "env.example.com"}


def test_load_env_raises_one_error_listing_every_line(tmp_path):
    (tmp_path / ".env").write_text("A=1\nLMS_HOSTNAME='x'\nexport DB_ROOT_PASSWORD=1\n")
    with pytest.raises(config.ConfigError) as exc:
        config.load_env(tmp_path, {})
    for fragment in ("line 1: unknown key A", "line 2: LMS_HOSTNAME", "line 3: 'export'"):
        assert fragment in str(exc.value)


def test_write_private_is_atomic_and_owner_only(tmp_path):
    target = tmp_path / ".env"
    config.write_private(target, "A=1\n")
    config.write_private(target, "A=2\n")
    assert target.read_text() == "A=2\n"
    assert target.stat().st_mode & 0o777 == 0o600
    assert not (tmp_path / ".env.tmp").exists()


def test_delivery_lists_each_service_with_its_variable_names():
    table = config.delivery()
    assert table["db"] == {"MARIADB_ROOT_PASSWORD": "DB_ROOT_PASSWORD"}
    assert table["frontend"] == {"FRAPPE_SITE_NAME_HEADER": "LMS_HOSTNAME"}
    assert "tools" not in table and "backend" not in table


def test_versions_file_uses_the_same_strict_syntax(request):
    repo = request.config.rootpath.parent
    versions = config.load_versions(repo)
    assert set(versions.values) == {k.name for k in config.committed_keys()}


# --- the cli entry points on top ---


def test_config_sample_prints_the_generated_sample(capsys, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    assert cli.main(["config", "sample"]) == 0
    assert capsys.readouterr().out == config.render_sample()


def test_config_show_masks_secrets_from_the_real_reader(tmp_path, monkeypatch, capsys):
    (tmp_path / ".env").write_text("DB_ROOT_PASSWORD=hunter2hunter2\nLMS_HOSTNAME=a.example.com\n")
    monkeypatch.chdir(tmp_path)
    assert cli.main(["config", "show"]) == 0
    out = capsys.readouterr().out
    assert "DB_ROOT_PASSWORD=*****" in out and "hunter2" not in out


def test_cli_error_for_a_bad_file_names_the_line_and_no_value(tmp_path, monkeypatch, capsys):
    (tmp_path / ".env").write_text('DB_ROOT_PASSWORD="hunter2hunter2"\n')
    monkeypatch.chdir(tmp_path)
    assert cli.main(["config", "show"]) == 1
    err = capsys.readouterr().err
    assert "line 1: DB_ROOT_PASSWORD" in err and "hunter2" not in err


def test_the_real_process_prints_no_secret_in_a_traceback(tmp_path):
    secret = "Zk3-very-secret-value-9"
    (tmp_path / ".env").write_text(f"DB_ROOT_PASSWORD={secret}\nLMS_HOSTNAME=a.b\n")
    code = (
        "import sys; from nile_tools import config, cli; "
        "config.install_masking(['" + secret + "']); "
        "raise RuntimeError('boom " + secret + "')"
    )
    done = subprocess.run(
        [sys.executable, "-c", code], cwd=tmp_path, capture_output=True, text=True, check=False
    )
    assert done.returncode == 1
    assert secret not in done.stderr and "boom *****" in done.stderr
