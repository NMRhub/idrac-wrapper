#!/usr/bin/env python3
import json
import os
from dataclasses import dataclass
from typing import NamedTuple, Callable

import redfish
from redfish.rest.v1 import ServerDownOrUnreachableError, RestResponse, HttpClient

from idrac import ilogger


class CommandReply(NamedTuple):
    """Reply from commands"""
    succeeded: bool
    msg: str


class IDrac:

    @dataclass
    class Summary:
        """Basic iDrac information"""
        idrac: str
        hostname: str
        service_tag: str
        power: str
        health: str

    def __init__(self, idracname, client:HttpClient):
        """idracname: hostname or IP"""
        self.idracname = idracname
        self.redfish_client = client
        self._system_json = None
        mq = json.loads(self.query('/redfish/v1/Managers'))
        members = mq['Members']
        if len(members) == 1:
            self.mgr_path = members[0].get('@odata.id')
        self.sys_path = '/redfish/v1/Systems/System.Embedded.1'

    @property
    def schemas(self):
        """Get schemas"""
        s = self.redfish_client.get('/redfish/v1/JSONSchemas')
        return s

    @property
    def _system(self):
        """System data, cached"""
        if self._system_json is None:
            resp = self.redfish_client.get(self.sys_path)
            self._system_json = json.loads(resp.text)
        return self._system_json

    @property
    def summary(self) -> Summary:
        """Get quick summary of iDrac"""
        s = self._system
        return IDrac.Summary(self.idracname, s['HostName'], s['SKU'], s['PowerState'], s['Status']['Health'])

    @property
    def xml_metdata(self):
        """get metadata as XML"""
        s = self.redfish_client.get('/redfish/v1/$metadata')
        return s.text

    def _message(self, reply_text: str) -> str:
        """Parse message from reply"""
        reply = json.loads(reply_text)
        try:
            extended = reply['error']['@Message.ExtendedInfo'][0]['Message']
            return extended
        except KeyError:
            ilogger.exception(f"{reply_text} parse")
            return reply_text

    def _read_reply(self, r: RestResponse, expected_status: int, good_message: str) -> CommandReply:
        """Read status and compare against expected status code"""
        if r.status == expected_status:
            return CommandReply(True, good_message)
        msg = self._message(r.text)
        ilogger.info(f"{good_message} {r.status} {msg}")
        return CommandReply(False, self._message(r.text))

    def query(self, query):
        """Arbitrary query"""
        s = self.redfish_client.get(query)
        if s.status == 200:
            return s.text
        return s.text

    # def server_control_profile(self):
    # """Future use, maybe"""
    #     url = self.mgr_path + '/Actions/Oem/EID_674_Manager.ExportSystemConfiguration'
    #     r = self.redfish_client.post(url)
    #     print(r)

    def _power(self, state: str, command: str) -> CommandReply:
        """Issue power command"""
        url = self.sys_path + '/Actions/ComputerSystem.Reset'
        payload = {'ResetType': state}
        r = self.redfish_client.post(url, body=payload)
        return self._read_reply(r, 204, command)

    def turn_off(self) -> CommandReply:
        """Turn off gracefully"""
        if self.summary.power == 'On':
            return self._power('GracefulShutdown', 'Shutdown')
        return CommandReply(True, 'Already off')

    def force_off(self) -> CommandReply:
        """Force off"""
        if self.summary.power == 'On':
            return self._power('ForceOff', 'Force shutdown')
        return CommandReply(True, 'Already off')

    def turn_on(self) -> CommandReply:
        """Turn on"""
        if self.summary.power == 'Off':
            return self._power('On', 'Turn on')
        return CommandReply(True, 'Already on')

    def mount_virtual(self, iso_url):
        """Mount a Virtual CD/DVD/ISO"""
        # http may not work, see https://github.com/dell/iDRAC-Redfish-Scripting/issues/225
        url = self.mgr_path + '/VirtualMedia/CD/Actions/VirtualMedia.InsertMedia'
        payload = {'Image': iso_url, 'Inserted': True, 'WriteProtected': True}
        ilogger.debug(f"{url} {payload}")
        r = self.redfish_client.post(url, body=payload)
        return self._read_reply(r, 204, f'Mounted {iso_url}')

    def eject_virtual(self) -> CommandReply:
        """Eject Virtual CD/DVD/ISO"""
        url = self.mgr_path + '/VirtualMedia/CD/Actions/VirtualMedia.EjectMedia'
        r = self.redfish_client.post(url, body={})
        return self._read_reply(r, 204, 'Ejected virtual media')

    def next_boot_virtual(self) -> CommandReply:
        """Set next boot to Virtual CD/DVD/ISO"""
        url = self.mgr_path + '/Actions/Oem/EID_674_Manager.ImportSystemConfiguration'
        payload = {"ShareParameters":
                       {"Target": "ALL"},
                   "ImportBuffer":
                       '<SystemConfiguration><Component FQDD="iDRAC.Embedded.1">'
                       '<Attribute Name="ServerBoot.1#BootOnce">Enabled</Attribute>'
                       '<Attribute Name="ServerBoot.1#FirstBootDevice">VCD-DVD</Attribute></Component></SystemConfiguration>'}
        r = self.redfish_client.post(url, body=payload)
        return self._read_reply(r, 202, 'Boot set to DVD')


class IdracAccessor:
    """Manager to store session data for iDRACs"""

    def __init__(self, session_data_filename=f"/tmp/idracacessor{os.getuid()}.dat"):
        self.state_data = {'sessions': {}}
        self.session_data = session_data_filename

    def __enter__(self):
        """Read session key data if present"""
        if os.path.isfile(self.session_data):
            with open(self.session_data) as f:
                self.state_data = json.load(f)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Store session keys"""
        with open(self.session_data, 'w', opener=lambda name, flags: os.open(name, flags, mode=0o600)) as f:
            json.dump(self.state_data, f)

    def connect(self, hostname:str, password_fn: Callable[[], str]) -> IDrac:
        """Connect with hostname or IP, method to return password if needed"""
        url = 'https://' + hostname
        sessionkey = self.state_data['sessions'].get(hostname, None)
        try:
            redfish_client = redfish.redfish_client(url, sessionkey=sessionkey)
        except ServerDownOrUnreachableError:
            sessionkey = None
            redfish_client = redfish.redfish_client(url, sessionkey=sessionkey)
        if sessionkey is None:
            pw = password_fn()
            redfish_client.login(auth='session', username='root', password=pw)
        self.state_data['sessions'][hostname] = redfish_client.get_session_key()
        return IDrac(hostname, redfish_client)
