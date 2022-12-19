#!/usr/bin/env python3
import json
import logging
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import NamedTuple, Callable, Any, Optional, Dict

import keyring
import redfish
from redfish.rest.v1 import ServerDownOrUnreachableError, RestResponse, HttpClient

from . import update
from .objects import VirtualMedia, JobStatus
from .update import update_parameters, get_idrac_version, download_image_payload, install_image_payload, \
    check_job_status,idrac_ip

ilogger = logging.getLogger('iDRAC')


class CommandReply(NamedTuple):
    """Reply from commands"""
    succeeded: bool
    msg: str
    results: Any = None
    job: Optional[int] = None


class IDrac:

    @dataclass
    class Summary:
        """Basic iDrac information"""
        idrac: str
        hostname: str
        service_tag: str
        power: str
        health: str

    def __init__(self, idracname, client:HttpClient,sessionkey=None):
        """idracname: hostname or IP"""
        self.idracname = idracname
        self.redfish_client = client
        mq = json.loads(self.query('/redfish/v1/Managers'))
        members = mq['Members']
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
                _,jstr = r.task_location.split('_')
                job_id = int(jstr)
            return CommandReply(True, good_message,None,job_id)
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

    def job_status(self,job_id: int):
        """Get job status for id"""
        r = self.redfish_client.get(f'/redfish/v1/TaskService/Tasks/JID_{job_id}')
        jstat =  JobStatus(r)
        if jstat.status in (200,202):
            return jstat
        raise ValueError(f'{jstat.status} {jstat.data}')

    def wait_for(self,job_id: int):
        """Wait for job to complete"""
        while self.job_status(job_id).status == 202:
            time.sleep(.1)

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
                    return self._read_reply(200,"get virtual")
            return CommandReply(True,"Devices",result)
        #else implicit
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

    def _check(self,response,code):
        if response.status != code:
            raise ValueError(response)
    def update(self,filename):
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
                                  '..','dell','SupportAssistCollectionLocalREDFISH.py')
        if not os.path.isfile(dellscript):
            raise ValueError(f"{dellscript} not found")
        cmd = (sys.executable,dellscript,'-ip',self.idracname,'-x',self.session_key,'--export','--data','0,1')
        print(' '.join(cmd))
        subprocess.run(cmd,input='y\n',text=True)




#        files = {'files': (filename, open(filename, 'rb'), 'multipart/form-data')}
#        url = self.updates.dict['HttpPushUri']
#        gresponse = self.redfish_client.get(url)
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
                 *, password_fn: Callable[[],str] = None):
        self.state_data = {'sessions': {}}
        self.session_data = session_data_filename
        self._password_fn = password_fn
        if os.path.isfile(self.session_data):
            with open(self.session_data) as f:
                self.state_data = json.load(f)

    def __enter__(self):
        """No op; keeps API backward compatible"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def connect(self, hostname:str, password_fn: Callable[[], str]=None) -> IDrac:
        """Connect with hostname or IP, method to return password if needed"""
        url = 'https://' + hostname
        sessionkey = self.state_data['sessions'].get(hostname, None)
        try:
            redfish_client = redfish.redfish_client(url, sessionkey=sessionkey)
        except ServerDownOrUnreachableError:
            sessionkey = None
            redfish_client = redfish.redfish_client(url, sessionkey=sessionkey)
        if sessionkey is None:
            print("Querying keyring",file=sys.stderr)
            pw = keyring.get_password('idrac','root')
            good_keyring = pw is not None
            if not good_keyring:
                print("No keyring password")
                if password_fn:
                    pw = password_fn()
                elif self._password_fn:
                    pw = self._password_fn()
                else:
                    raise ValueError("Password function required")
            redfish_client.login(auth='session', username='root', password=pw)
            self.state_data['sessions'][hostname] = sessionkey = redfish_client.get_session_key()
            with open(self.session_data, 'w', opener=lambda name, flags: os.open(name, flags, mode=0o600)) as f:
                json.dump(self.state_data, f)
            if not good_keyring:
                keyring.set_password('idrac','root',pw)
        return IDrac(hostname, redfish_client,sessionkey)
