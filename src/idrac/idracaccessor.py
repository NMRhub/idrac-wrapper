#!/usr/bin/env python3
import json
import os
import sys
from typing import Callable

import keyring
import redfish
from keyring.errors import KeyringLocked
from redfish.rest.v1 import ServerDownOrUnreachableError, InvalidCredentialsError

from idrac import ilogger
from idrac.idracclass import IDrac


class IdracAccessor:
    """Manager to store session data for iDRACs"""

    def __init__(self, session_data_filename=f"/var/tmp/idracacessor{os.getuid()}.dat",
                 *, login:str = 'root'):
        self.state_data = {'sessions': {}}
        self.session_data = session_data_filename
        self.login_account = login
        if os.path.isfile(self.session_data):
            with open(self.session_data) as f:
                self.state_data = json.load(f)

    def __enter__(self):
        """No op; keeps API backward compatible"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            self.redfish_client.logout()
        except Exception:
            ilogger.exception("logout error")


    def _login(self,hostname,starting_pw):
        pw  = starting_pw
        while True:
            try:
                ilogger.debug(f"Trying {hostname}  {self.login_account}, password {pw}")
                self.redfish_client.login(auth='session', username=self.login_account, password=pw)
                return pw
            except InvalidCredentialsError as ice:
                if '401' in str(ice):
                    print(f"Password {pw} failed for {self.login_account}")
                    pw = self.password_fn()

    def connect(self, hostname: str, password_fn: Callable[[], str] ) -> IDrac:
        """Connect with hostname or IP, method to return password if needed"""
        self.password_fn = password_fn
        url = 'https://' + hostname
        sessionkey = None
        try:
            self.redfish_client = redfish.redfish_client(url, sessionkey=sessionkey)
            ilogger.debug(f"Connect {hostname} with session key")
        except ServerDownOrUnreachableError:
            self.redfish_client = redfish.redfish_client(url, sessionkey=(sessionkey := None))
        if sessionkey is None:
            pw = None
            try:
                pw = keyring.get_password('idrac', self.login_account)
                good_keyring = pw is not None
            except KeyringLocked:
                print("Keyring locked", file=sys.stderr)
                good_keyring = False
            if not good_keyring:
                print("No keyring password")
                pw = self.password_fn()
            pw = self._login(hostname,pw)
            ilogger.debug(f"Connected {hostname} as {self.login_account}, saved session key")
            with open(self.session_data, 'w', opener=lambda name, flags: os.open(name, flags, mode=0o600)) as f:
                json.dump(self.state_data, f)
            try:
                if not good_keyring:
                    ilogger.debug(f"Saving idrac {self.login_account} password to keyring")
                    keyring.set_password('idrac', self.login_account, pw)
            except KeyringLocked:
                pass
        return IDrac(hostname, self.redfish_client, sessionkey)
