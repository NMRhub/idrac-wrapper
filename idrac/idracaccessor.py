#!/usr/bin/env python3
import json
import logging
import os
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import NamedTuple, Callable, Any, Optional, Generator, Mapping, ClassVar

import keyring
import redfish
from keyring.errors import KeyringLocked
from redfish.rest.v1 import ServerDownOrUnreachableError, RestResponse, HttpClient, InvalidCredentialsError

from . import update
from .objects import VirtualMedia, JobStatus
from .update import update_parameters, get_idrac_version, download_image_payload, install_image_payload, \
    check_job_status

ilogger = logging.getLogger('iDRAC')


class CommandReply(NamedTuple):
    """Reply from commands"""
    succeeded: bool
    msg: str
    results: Any = None
    job: Optional[int] = None


@dataclass
class Account:
    id: int
    enabled: bool
    name: str
    role: str


ROLES = ('Administrator', 'Operator', 'ReadOnly', 'None')


class IDrac:
    @dataclass
    class Summary:
        """Basic iDrac information"""
        idrac: str
        hostname: str
        service_tag: str
        power: str
        health: str
        only_ip : ClassVar[bool] = False

        def __post_init__(self):
            self.ip = socket.gethostbyname(self.idrac)


        def __str__(self):
            if self.only_ip:
                return f"{self.ip} {self.hostname} {self.service_tag} {self.power} health {self.health}"
            return f"iDRAC: {self.idrac} {self.ip} {self.service_tag} server: {self.power} health {self.health}"



    def __init__(self, idracname, client: HttpClient, sessionkey=None):
        """idracname: hostname or IP"""
        self.idracname = idracname
        self.redfish_client = client
        mq = json.loads(self.query('/redfish/v1/Managers'))
        members = mq['Members']  # failed once 2023-Apr-4
        if len(members) == 1:
            self.mgr_path = members[0].get('@odata.id')
        self.sys_path = '/redfish/v1/Systems/System.Embedded.1'
        self.session_key = sessionkey

    @property
    def schemas(self):
        """Get schemas"""
        s = self.redfish_client.get('/redfish/v1/JSONSchemas')
        return s

    @property
    def updates(self):
        """Get schemas"""
        s = self.redfish_client.get('/redfish/v1/UpdateService')
        return s

    @property
    def _system(self):
        """System data"""
        resp = self.redfish_client.get(self.sys_path)
        return json.loads(resp.text)

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
        job_id = 0
        if r.status == expected_status:
            if r.task_location:
                _, jstr = r.task_location.split('_')
                job_id = int(jstr)
            return CommandReply(True, good_message, None, job_id)
        msg = self._message(r.text)
        ilogger.info(f"{good_message} {r.status} {msg}")
        return CommandReply(False, self._message(r.text))

    def query(self, query):
        """Arbitrary query"""
        s = self.redfish_client.get(query)
        return s.text

    def patch(self, url:str,data:Mapping):
        s = self.redfish_client.patch(url,body=data)
        return s

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

    def job_status(self, job_id: int, *, allow404: bool = False) -> JobStatus:
        """Get job status for id"""
        r = self.redfish_client.get(f'/redfish/v1/TaskService/Tasks/JID_{job_id}')
        jstat = JobStatus(r)
        if jstat.status in (200, 202):
            return jstat
        if allow404 and jstat.status == 404:
            return jstat
        raise ValueError(f'{jstat.status} {jstat.data}')

    def wait_for(self, job_id: int, *, allow404: bool = False) -> JobStatus:
        """Wait for job to complete"""
        while (jstat := self.job_status(job_id, allow404=allow404)).status == 202:
            time.sleep(.1)
        return jstat

    def get_virtual(self):
        url = self.mgr_path + '/VirtualMedia'
        r = self.redfish_client.get(url)
        if r.status == 200:
            result = []
            devices = []
            data = json.loads(r.text)
            for member in data['Members']:
                ds = member['@odata.id'].split('/')
                devices.append(ds[-1])
            for dev in devices:
                url = self.mgr_path + '/VirtualMedia/' + dev
                r2 = self.redfish_client.get(url)
                if r.status == 200:
                    rdata = json.loads(r2.text)
                    result.append(VirtualMedia(rdata))
                else:
                    return self._read_reply(200, "get virtual")
            return CommandReply(True, "Devices", result)
        # else implicit
        return self._read_reply(200, "get virtual")

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

    def next_boot_pxe(self) -> CommandReply:
        """Set next boot to PXE"""
        url = self.mgr_path + '/Actions/Oem/EID_674_Manager.ImportSystemConfiguration'
        payload = {"ShareParameters":
                       {"Target": "ALL"},
                   "ImportBuffer":
                       '<SystemConfiguration><Component FQDD="iDRAC.Embedded.1">'
                       '<Attribute Name="ServerBoot.1#BootOnce">Enabled</Attribute>'
                       '<Attribute Name="ServerBoot.1#FirstBootDevice">PXE</Attribute></Component></SystemConfiguration>'}
        r = self.redfish_client.post(url, body=payload)
        return self._read_reply(r, 202, 'Boot set to PXE')

    def _check(self, response, code):
        if response.status != code:
            raise ValueError(response)

    def update(self, filename):
        update.idrac_ip = self.idracname
        update_parameters['ip'] = self.idracname
        update_parameters['u'] = None
        update_parameters['p'] = None
        update_parameters['x'] = self.session_key
        update_parameters['reboot'] = True

        fpath = os.path.abspath(filename)
        update_parameters['location'] = os.path.dirname(fpath)
        update_parameters['image'] = os.path.basename(fpath)
        get_idrac_version()
        download_image_payload()
        install_image_payload()
        check_job_status()

    def tsr(self):
        if 'DISPLAY' not in os.environ:
            raise ValueError(
                "DISPLAY not set. Run in graphical terminal to allow download with browser after collection")

        dellscript = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  '..', 'dell', 'SupportAssistCollectionLocalREDFISH.py')
        if not os.path.isfile(dellscript):
            raise ValueError(f"{dellscript} not found")
        cmd = (sys.executable, dellscript, '-ip', self.idracname, '-x', self.session_key,
               '--accept', '--export', '--data', '0,1')
        print(' '.join(cmd))
        subprocess.run(cmd, input='y\n', text=True)

    def accounts(self) -> Generator[Account, None, None]:
        y = '/redfish/v1/Managers/iDRAC.Embedded.1/Accounts?$expand=*($levels=1)'
        # mq = json.loads(self.query('/redfish/v1/Managers/iDRAC.Embedded.1/Accounts?$expand=*($levels=1'))
        mq = json.loads(self.query(y))
        for m in mq['Members']:
            if (d := m.get('Description',None)) is not None and d != 'User Account':
                raise ValueError('Unexpected type')
            yield Account(int(m['Id']), m['Enabled'], m['UserName'], m['RoleId'])

    def unused_account_slot(self):
        current: Account
        for current in self.accounts():
            if current.id > 1 and not current.enabled and current.name == '':
                return current.id
        raise ValueError("All account slots in use")


    def create_account(self, slot: int, name: str, password: str, role: str):
        if not role in ROLES:
            raise ValueError(f"Role {role} must in bin {','.join(ROLES)}")
        existing = list(self.accounts())
        used = [e for e in existing if e.name == name]
        if used:
            ilogger.warning(f"{self.idracname} already has account {name}")
            return
        for current in existing:
            if current.id == slot:
                break
        else:
            raise ValueError(f"slot {slot} not found")

        # noinspection PyUnboundLocalVariable
        if current.enabled or current.name != '':
            raise ValueError(f"Account {slot} in use")
        url = f'/redfish/v1/Managers/iDRAC.Embedded.1/Accounts/{slot}'
        payload = {'UserName': name,
                   'Password': password,
                   'RoleId': role,
                   'Enabled': True}
        r = self.patch(url,payload)
        if r.status == 200 and hasattr(r,"text"):
            print(r.text)
        else:
            ilogger.warning(r)

    def set_password(self, name: str, password: str):
        existing = list(self.accounts())
        used = [e for e in existing if e.name == name]
        if not used:
            ilogger.warning(f"{self.idracname} does not have account {name}" )
            return
        slot = used[0].id
        url = f'/redfish/v1/Managers/iDRAC.Embedded.1/Accounts/{slot}'
        payload = {'Password': password}
        r = self.patch(url,payload)
        if r.status == 200 and hasattr(r,"text"):
            print(r.text)
        else:
            ilogger.warning(r)

    
    def _archive_dir(self,spec:str,fetch:bool):
        """Set archive dir or fetch last"""
        if fetch:
            url = '/redfish/v1/Dell/Managers/iDRAC.Embedded.1/DellLCService/Actions/DellLCService.SupportAssistExportLastCollection'
        else:
            url = '/redfish/v1/Dell/Managers/iDRAC.Embedded.1/DellLCService/Actions/DellLCService.SupportAssistCollection'
        ip, exprt = spec.split(':')
        payload = {"IPAddress":ip,
                   "ShareName":exprt,
                   "ShareType":'NFS'
                   }
        r = self.redfish_client.post(url,body=payload)
        if r.status == 202 and hasattr(r,"text"):
            ilogger.info(f"NFS archive set to {ip} {exprt}")
            print(r.text)
        else:
            ilogger.warning(r)

    def set_archive_dir(self,spec:str):
        """Set archive dir"""
        self._archive_dir(spec,False)

    def get_last_collection(self,spec:str):
        """Fetch last"""
        self._archive_dir(spec,True)

#        files = {'files': (filename, open(filename, 'rb'), 'multipart/form-data')}
#        url = self.updates.dict['HttpPushUri']
#        gresponse = self.redfish_client.get(url)kk
#        self._check(gresponse,200)
#
#        etag = gresponse.getheader('ETag')
#
#
#        headers = {'Content-Type': 'multipart/form-data','if-match':etag}
#        response = self.redfish_client.post(url,body=files,headers=headers)
#        if response.status == 503:
#            avail = self.redfish_client.get('/redfish/v1/UpdateService/FirmwareInventory/Available')
#            print(avail)
#            id = 'Available-107649-3.72__RAID.Backplane.Firmware.2'
#        else:
#            self._check(response,201)
#            id = response.dict['Id']
#        payload = {f"ImageURI":f"{url}/{id}","@Redfish.OperationApplyTime": "Immediate"}
#        jdata = json.dumps(payload)
#        iurl = 'redfish/v1/UpdateService/Actions/UpdateService.SimpleUpdate'
#        r = self.redfish_client.post(iurl,body=jdata)
#        print(r)


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
