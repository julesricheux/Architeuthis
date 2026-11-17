# -*- coding: utf-8 -*-
"""
Credentials of the data providers that need an account.

Save each credential once, and it is used from then on:

    python -m architeuthis.credentials set CMEMS_USER CMEMS_PWD

`save_credential` stores it in the credential store of the operating
system through `keyring`: Windows Credential Manager, the macOS
Keychain, or the Secret Service on Linux. It is encrypted there, never
in a plain text file.

A credential is looked up when a download needs it, never at import:

1. in its environment variables, which override the stored value for a
   session, a CI job or a server without credential store;
2. in the credential store.

Copernicus Marine and the Climate Data Store also keep working with
their own files, `copernicusmarine login` and `~/.cdsapirc`, when
Architeuthis finds nothing.

Created on Mon Nov 16 10:00:00 2026

@author: jrich
"""

import argparse
import os
import sys
from getpass import getpass
from typing import NamedTuple, Optional, Sequence

from architeuthis.common import status

KEYRING_SERVICE = "architeuthis"


class Credential(NamedTuple):
    """
    A credential that Architeuthis can look up.

    Args:
        description: What to give, as the provider calls it.
        variables: Environment variables that hold it, in the order
            they are read. The first is its name in the credential
            store.
        secret: Whether it is hidden when typed.
    """

    description: str
    variables: tuple[str, ...]
    secret: bool = True


CREDENTIALS = {
    "CDS_API_KEY": Credential(
        description="Climate Data Store Personal Access Token",
        variables=("CDS_API_KEY", "CDSAPI_KEY"),
    ),
    "CMEMS_USER": Credential(
        description="Copernicus Marine username",
        variables=("CMEMS_USER", "COPERNICUSMARINE_SERVICE_USERNAME"),
        secret=False,
    ),
    "CMEMS_PWD": Credential(
        description="Copernicus Marine password",
        variables=("CMEMS_PWD", "COPERNICUSMARINE_SERVICE_PASSWORD"),
    ),
    "EUMDAC_KEY": Credential(
        description="EUMETSAT Consumer Key",
        variables=("EUMDAC_KEY", "EUMDAC_USER"),
    ),
    "EUMDAC_SECRET": Credential(
        description="EUMETSAT Consumer Secret",
        variables=("EUMDAC_SECRET", "EUMDAC_PWD"),
    ),
}


class MissingCredentialError(RuntimeError):
    """
    A provider needs a credential that was found nowhere.
    """


def _credential(name: str) -> Credential:
    try:
        return CREDENTIALS[name]
    except KeyError:
        raise KeyError(f"Unknown credential {name!r}. Known: {', '.join(CREDENTIALS)}.") from None


def _keyring():
    # Imported on use only: importing Architeuthis never touches the credential store.
    import keyring

    return keyring


def _lookup(name: str) -> tuple[Optional[str], Optional[str]]:
    """
    The value of a credential and where it was found.
    """
    for variable in _credential(name).variables:
        value = os.environ.get(variable)
        if value:
            return value, f"environment variable {variable}"

    keyring = _keyring()
    try:
        value = keyring.get_password(KEYRING_SERVICE, name)
    except keyring.errors.KeyringError:
        # No usable credential store, a Linux server for example: only the
        # environment variables are left.
        value = None
    if value:
        return value, "credential store"
    return None, None


def _overriding_variables(name: str) -> list[str]:
    """
    Environment variables of a credential that are set in this session.

    Any of them is read before the credential store.
    """
    return [variable for variable in _credential(name).variables if os.environ.get(variable)]


def get_credential(name: str) -> Optional[str]:
    """
    The value of a credential, or None if it is found nowhere.

    Its environment variables are read first, then the credential store.
    Never print or log the result.

    Args:
        name: Name of the credential, a key of `CREDENTIALS`.

    Returns:
        The value, or None.
    """
    return _lookup(name)[0]


def credential_sources() -> dict[str, Optional[str]]:
    """
    Where each credential is found, without its value.

    Returns:
        A dict from each name of `CREDENTIALS` to its source, such as
        "credential store" or "environment variable CMEMS_PWD", or None
        when it is missing.

    Example:
        >>> credential_sources()["CMEMS_PWD"]
        'credential store'
    """
    return {name: _lookup(name)[1] for name in CREDENTIALS}


def save_credential(name: str, value: Optional[str] = None) -> None:
    """
    Store a credential in the credential store of the operating system.

    It is then found by every later session, until it is deleted or
    saved again. The value is read back from the store, so that a save
    that did not take raises an error.

    An environment variable of the same credential would still be read
    first, and hide the saved value. Such variables are removed from
    this session, with a ⚠️ status naming them: they stay set for new
    sessions until they are deleted where they were defined (the user
    environment variables of Windows, `setx`, a shell profile or
    `conda env config vars`).

    Args:
        name: Name of the credential, a key of `CREDENTIALS`.
        value: The value. If None, it is asked for, hidden when it is
            secret, so that it appears neither in the code nor in the
            history of the console.

    Example:
        >>> save_credential("CMEMS_PWD")
        Copernicus Marine password (CMEMS_PWD):
    """
    credential = _credential(name)
    if value is None:
        prompt = f"{credential.description} ({name}): "
        value = getpass(prompt) if credential.secret else input(prompt)
    value = value.strip()
    if not value:
        raise ValueError(f"No value given for {name}.")

    keyring = _keyring()
    try:
        keyring.set_password(KEYRING_SERVICE, name, value)
        stored = keyring.get_password(KEYRING_SERVICE, name)
    except keyring.errors.KeyringError as error:
        raise RuntimeError(
            f"No credential store is available to save {name} ({error}). "
            f"Set the environment variable {credential.variables[0]} instead."
        ) from error
    if stored != value:
        raise RuntimeError(
            f"{name} was not saved: the credential store "
            f"({type(keyring.get_keyring()).__name__}) still returns another value."
        )
    status(f"✅ {name} saved in the credential store.")

    # Otherwise the old value, in the environment, would still be the one read.
    for variable in _overriding_variables(name):
        del os.environ[variable]
        status(
            f"⚠️ The environment variable {variable} held another {name} and hid "
            "the saved one: removed from this session. Delete it where it is "
            "defined (Windows user environment variables, setx, shell profile, "
            "conda env config vars), or new sessions will still read it."
        )


def delete_credential(name: str) -> bool:
    """
    Remove a credential from the credential store.

    Its environment variables are left as they are.

    Args:
        name: Name of the credential, a key of `CREDENTIALS`.

    Returns:
        Whether a stored value was removed.
    """
    _credential(name)
    keyring = _keyring()
    try:
        keyring.delete_password(KEYRING_SERVICE, name)
    except keyring.errors.KeyringError:
        # PasswordDeleteError when nothing was stored, or no credential store.
        return False
    status(f"➖ {name} removed from the credential store.")
    return True


def require_credentials(
    *names: str,
    provider: str,
    fallback_files: Sequence[str] = (),
) -> tuple[Optional[str], ...]:
    """
    The values of the credentials a provider needs, or a clear error.

    Called just before a download, so that a missing credential stops
    it at once, with the names to set.

    Args:
        *names: Names of the credentials, keys of `CREDENTIALS`.
        provider: Name of the provider, for the messages.
        fallback_files: Files where the client of the provider finds
            its own credentials. If all the credentials are missing and
            one of these files exists, the values are None and the
            client reads its file.

    Returns:
        The values, in the order of `names`.

    Raises:
        MissingCredentialError: If a credential is missing and no
            fallback file applies.
    """
    values = tuple(get_credential(name) for name in names)
    missing = [name for name, value in zip(names, values) if value is None]
    if not missing:
        return values

    if len(missing) == len(names):
        for path in fallback_files:
            if os.path.exists(path):
                return values

    variables = ", ".join(_credential(name).variables[0] for name in missing)
    message = (
        f"{provider} needs {variables}, found neither in the environment nor in the credential store. "
        f"Save {'it' if len(missing) == 1 else 'them'} once with: python -m architeuthis.credentials set {' '.join(missing)}"
    )
    status(f"⚠️ {message}")
    raise MissingCredentialError(message)


def _main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m architeuthis.credentials",
        description="Save, check or remove the credentials of the data providers.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status", help="show where each credential is found, without its value")
    setter = commands.add_parser("set", help="ask for credentials and save them in the credential store")
    setter.add_argument("names", nargs="+", choices=list(CREDENTIALS), metavar="NAME")
    deleter = commands.add_parser("delete", help="remove credentials from the credential store")
    deleter.add_argument("names", nargs="+", choices=list(CREDENTIALS), metavar="NAME")
    arguments = parser.parse_args(argv)

    if arguments.command == "status":
        for name, source in credential_sources().items():
            print(f"{name:<14} {source or 'missing'}")
    elif arguments.command == "set":
        for name in arguments.names:
            save_credential(name)
    else:
        for name in arguments.names:
            if not delete_credential(name):
                print(f"{name} was not in the credential store.")
    return 0


if __name__ == "__main__":
    sys.exit(_main())
