#!/usr/bin/env python3
import json
import os
import sys
from functools import cached_property
from typing import Callable

import keyring
import redfish
from keyring.errors import KeyringLocked
from redfish.rest.v1 import ServerDownOrUnreachableError, InvalidCredentialsError, RetriesExhaustedError

from idrac import ilogger
from idrac.idracclass import IDrac
from idrac.connect8 import make_dhe_compatible_context, SSLContextAdapter
_SESSIONS = 'sessions'
_SMALL_KEYS  = 'small_keys'


#requests.packages.urllib3.disable_warnings()
#requests.packages.urllib3.util.ssl_.DEFAULT_CIPHERS += ':HIGH:!DH:!aNULL'
class IdracAccessor:
    """Manager to store session data for iDRACs"""

    def __init__(self, session_data_filename=f"/var/tmp/idracacessor{os.getuid()}.dat",
                 *, login:str = 'root'):
        self.state_data = {_SESSIONS: {}}
        self.session_data = session_data_filename
        self.login_account = login
        if os.path.isfile(self.session_data):
            with open(self.session_data) as f:
                self.state_data = json.load(f)
        else:
            self.state_data = {}
        if not _SESSIONS in self.state_data:
            self.state_data[_SESSIONS] = {}
        if not _SMALL_KEYS in self.state_data:
            self.state_data[_SMALL_KEYS] = []

    def sync_state(self):
        with open(self.session_data, 'w', opener=lambda name, flags: os.open(name, flags, mode=0o600)) as f:
            json.dump(self.state_data, f)

    def __enter__(self):
        """No op; keeps API backward compatible"""
        self.redfish_client = None
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            if self.redfish_client is not None:
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

    def is_key_too_small(self,e:Exception)->bool:
        we = e
        while we is not None:
            if 'DH_KEY_TOO_SMALL' in str(we):
                return True
            we = we.__cause__
        return False

    @cached_property
    def small_key_adapater(self)->SSLContextAdapter:
        ctx = make_dhe_compatible_context(seclevel=0, verify=False)
        return SSLContextAdapter(ctx)

    def make_right_client(self,url,sessionkey):
        if url not in self.state_data[_SMALL_KEYS]:
            adapter = None
        else:
            adapter = self.small_key_adapater
        try:
            client = redfish.redfish_client(url, sessionkey=sessionkey, max_retry=1,https_adapter=adapter)
            return client
        except Exception as e:
            if self.is_key_too_small(e):
                self.state_data[_SMALL_KEYS].append(url)
                self.sync_state()
                return self.make_right_client(url,sessionkey)
            raise

    def connect(self, hostname: str, password_fn: Callable[[], str] ) -> IDrac:
        """Connect with hostname or IP, method to return password if needed"""
        self.password_fn = password_fn
        url = 'https://' + hostname
        try:
            sessionkey = self.state_data[_SESSIONS][hostname]
        except:
            sessionkey = None
        try:
            self.redfish_client = self.make_right_client(url, sessionkey=sessionkey)
            ilogger.debug(f"Connect {hostname} with session key {sessionkey}")
        except ServerDownOrUnreachableError:
            self.redfish_client = self.make_right_client(url, sessionkey=(sessionkey := None))
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
            sessionkey = self.redfish_client.get_session_key()
            self.state_data[_SESSIONS][hostname] = sessionkey
            with open(self.session_data, 'w', opener=lambda name, flags: os.open(name, flags, mode=0o600)) as f:
                json.dump(self.state_data, f)
            ilogger.debug(f"Connected {hostname} as {self.login_account}, saved session key")
            try:
                if not good_keyring:
                    ilogger.debug(f"Saving idrac {self.login_account} password to keyring")
                    keyring.set_password('idrac', self.login_account, pw)
            except KeyringLocked:
                pass
        return IDrac(hostname, self.redfish_client, sessionkey)
