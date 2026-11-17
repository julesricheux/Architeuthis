"""Credentials: saved once in the credential store, read when a download needs them."""

from unittest.mock import patch

import keyring
import keyring.backend
import keyring.errors
import pytest

from architeuthis import credentials
from architeuthis.credentials import (
    CREDENTIALS,
    KEYRING_SERVICE,
    MissingCredentialError,
    credential_sources,
    delete_credential,
    get_credential,
    require_credentials,
    save_credential,
)


class MemoryKeyring(keyring.backend.KeyringBackend):
    """A credential store that lives in this test only."""

    priority = 1

    def __init__(self):
        super().__init__()
        self.passwords = {}

    def get_password(self, service, username):
        return self.passwords.get((service, username))

    def set_password(self, service, username, password):
        self.passwords[(service, username)] = password

    def delete_password(self, service, username):
        if self.passwords.pop((service, username), None) is None:
            raise keyring.errors.PasswordDeleteError(username)


class NoKeyring(keyring.backend.KeyringBackend):
    """A machine without credential store, a Linux server for example."""

    priority = 1

    def get_password(self, service, username):
        raise keyring.errors.NoKeyringError("no backend")

    def set_password(self, service, username, password):
        raise keyring.errors.NoKeyringError("no backend")

    def delete_password(self, service, username):
        raise keyring.errors.NoKeyringError("no backend")


@pytest.fixture
def store():
    previous = keyring.get_keyring()
    memory = MemoryKeyring()
    keyring.set_keyring(memory)
    yield memory.passwords
    keyring.set_keyring(previous)


@pytest.fixture
def no_store():
    previous = keyring.get_keyring()
    keyring.set_keyring(NoKeyring())
    yield
    keyring.set_keyring(previous)


def test_a_saved_credential_is_found_later(store):
    save_credential("CMEMS_PWD", "my-password")

    assert store[(KEYRING_SERVICE, "CMEMS_PWD")] == "my-password"
    assert get_credential("CMEMS_PWD") == "my-password"
    assert credential_sources()["CMEMS_PWD"] == "credential store"


def test_the_environment_overrides_the_store(store, monkeypatch):
    save_credential("CMEMS_PWD", "stored")
    monkeypatch.setenv("CMEMS_PWD", "for-this-session")

    assert get_credential("CMEMS_PWD") == "for-this-session"
    assert credential_sources()["CMEMS_PWD"] == "environment variable CMEMS_PWD"


def test_the_environment_is_read_on_each_call(store, monkeypatch):
    assert get_credential("CDS_API_KEY") is None

    monkeypatch.setenv("CDS_API_KEY", "set-after-import")

    assert get_credential("CDS_API_KEY") == "set-after-import"


@pytest.mark.parametrize(
    "name, variable",
    [
        ("CDS_API_KEY", "CDSAPI_KEY"),
        ("CMEMS_USER", "COPERNICUSMARINE_SERVICE_USERNAME"),
        ("CMEMS_PWD", "COPERNICUSMARINE_SERVICE_PASSWORD"),
        ("EUMDAC_KEY", "EUMDAC_USER"),
        ("EUMDAC_SECRET", "EUMDAC_PWD"),
    ],
)
def test_other_names_of_a_credential_are_read(store, monkeypatch, name, variable):
    monkeypatch.setenv(variable, "value")

    assert get_credential(name) == "value"


def test_an_empty_variable_counts_as_missing(store, monkeypatch):
    monkeypatch.setenv("CMEMS_PWD", "")

    assert get_credential("CMEMS_PWD") is None


def test_a_missing_value_is_asked_for_hidden(store):
    with patch.object(credentials, "getpass", return_value=" typed \n") as typed:
        save_credential("EUMDAC_SECRET")

    assert "EUMETSAT Consumer Secret" in typed.call_args.args[0]
    assert store[(KEYRING_SERVICE, "EUMDAC_SECRET")] == "typed"


def test_a_username_is_asked_for_in_clear(store):
    with patch("builtins.input", return_value="me"), patch.object(credentials, "getpass") as hidden:
        save_credential("CMEMS_USER")

    hidden.assert_not_called()
    assert store[(KEYRING_SERVICE, "CMEMS_USER")] == "me"


def test_an_empty_value_is_refused(store):
    with pytest.raises(ValueError):
        save_credential("CMEMS_PWD", "  ")

    assert store == {}


def test_an_unknown_name_is_refused(store):
    with pytest.raises(KeyError, match="CMEMS_PWD"):
        save_credential("CMEMS_PASSWORD", "x")


def test_saving_never_shows_the_value(store, capsys):
    save_credential("CMEMS_PWD", "my-password")

    assert "my-password" not in capsys.readouterr().out


def test_delete_removes_the_stored_value(store):
    save_credential("CMEMS_PWD", "my-password")

    assert delete_credential("CMEMS_PWD") is True
    assert delete_credential("CMEMS_PWD") is False
    assert get_credential("CMEMS_PWD") is None


def test_without_credential_store_the_environment_still_works(no_store, monkeypatch):
    assert get_credential("CMEMS_PWD") is None

    monkeypatch.setenv("CMEMS_PWD", "from-the-environment")

    assert get_credential("CMEMS_PWD") == "from-the-environment"
    assert delete_credential("CMEMS_PWD") is False


def test_without_credential_store_saving_names_the_variable(no_store):
    with pytest.raises(RuntimeError, match="CMEMS_PWD"):
        save_credential("CMEMS_PWD", "x")


def test_require_returns_the_values_in_order(store, monkeypatch):
    save_credential("CMEMS_PWD", "password")
    monkeypatch.setenv("CMEMS_USER", "user")

    assert require_credentials("CMEMS_USER", "CMEMS_PWD", provider="Copernicus Marine") == ("user", "password")


def test_require_names_what_is_missing_and_how_to_save_it(store, monkeypatch, capsys):
    monkeypatch.setenv("CMEMS_USER", "user")

    with pytest.raises(MissingCredentialError) as error:
        require_credentials("CMEMS_USER", "CMEMS_PWD", provider="Copernicus Marine")

    assert "needs CMEMS_PWD" in str(error.value)
    assert "python -m architeuthis.credentials set CMEMS_PWD" in str(error.value)
    assert capsys.readouterr().out.startswith("⚠️")


def test_require_leaves_a_complete_fallback_to_the_client(store, tmp_path):
    login = tmp_path / "login"
    login.write_text("")

    values = require_credentials("CMEMS_USER", "CMEMS_PWD", provider="Copernicus Marine", fallback_files=[login])

    assert values == (None, None)


def test_require_does_not_mix_a_partial_set_with_a_fallback(store, monkeypatch, tmp_path):
    login = tmp_path / "login"
    login.write_text("")
    monkeypatch.setenv("CMEMS_USER", "user")

    with pytest.raises(MissingCredentialError):
        require_credentials("CMEMS_USER", "CMEMS_PWD", provider="Copernicus Marine", fallback_files=[login])


def test_eumetsat_reads_its_credentials_when_downloading(store, monkeypatch):
    from architeuthis.satellite import ASCATData

    data = ASCATData("ascat", start="2025-01-01", end="2025-01-02")
    save_credential("EUMDAC_KEY", "key")
    monkeypatch.setenv("EUMDAC_PWD", "secret")

    with patch("architeuthis.satellite.eumdac") as eumdac:
        data._locate_data()

    eumdac.AccessToken.assert_called_once_with(("key", "secret"))
    assert "secret" not in repr(vars(data))


def test_eumetsat_without_credentials_stops_before_connecting(store):
    from architeuthis.satellite import ASCATData

    data = ASCATData("ascat", start="2025-01-01", end="2025-01-02")

    with patch("architeuthis.satellite.eumdac") as eumdac, pytest.raises(MissingCredentialError, match="EUMDAC_KEY, EUMDAC_SECRET"):
        data._locate_data()

    eumdac.AccessToken.assert_not_called()


def test_command_line_saves_shows_and_deletes(store, capsys):
    with patch.object(credentials, "getpass", return_value="secret"):
        credentials._main(["set", "CDS_API_KEY"])
    credentials._main(["status"])
    shown = capsys.readouterr().out
    credentials._main(["delete", "CDS_API_KEY"])

    assert store == {}
    assert "CDS_API_KEY    credential store" in shown
    assert "CMEMS_PWD      missing" in shown
    assert "secret" not in shown


def test_every_credential_has_its_own_name_first():
    for name, credential in CREDENTIALS.items():
        assert credential.variables[0] == name
