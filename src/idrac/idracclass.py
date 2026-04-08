#!/usr/bin/env python3
import json
import os
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from functools import cached_property
from typing import NamedTuple, Any, Optional, Generator, Mapping, ClassVar

from redfish.rest.v1 import RestResponse, HttpClient

from idrac import ilogger, update, PortInfo
from idrac.objects import VirtualMedia, JobStatus
from idrac.update import update_parameters, get_idrac_version, download_image_payload, install_image_payload, \
    check_job_status


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
    SUBSYSTEM = {
        'idrac':'/redfish/v1/Managers/iDRAC.Embedded.1/Oem/Dell/DellAttributes/iDRAC.Embedded.1',
        'bios': '/redfish/v1/Systems/System.Embedded.1/Bios',
        'system':'/redfish/v1/Managers/iDRAC.Embedded.1/Oem/Dell/DellAttributes/System.Embedded.1',
        'lifecycle': '/redfish/v1/Managers/iDRAC.Embedded.1/Oem/Dell/DellAttributes/LifecycleController.Embedded.1',
        'network': 'get_network:set_network'
    }

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
            return f"iDRAC: {self.idrac} {self.ip} {self.hostname} {self.service_tag} server: {self.power} health {self.health}"



    def __init__(self, idracname, client: HttpClient, sessionkey=None):
        """idracname: hostname or IP"""
        self.idracname = idracname
        self.redfish_client = client
        mq = json.loads(self.query('/redfish/v1/Managers'))
        members = mq['Members']  # failed once 2023-Apr-4
        if len(members) == 1:
            self.mgr_path = members[0].get('@odata.id')
        else:
            raise ValueError('no manager path')
        self.sys_path = '/redfish/v1/Systems/System.Embedded.1'
        self.session_key = sessionkey

    def __getattr__(self, item):
        """Get attribute from _system if not defined on class"""
        if (v := self._system.get(item,None))  is not None:
            return v
        raise AttributeError(f"no attribute {item}")


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

    def _select_attribute(self,path:str,attribute:str | None)->str:
        apath = f"{path}?$select=Attributes"
        if attribute is not None:
            attribute = attribute if attribute.startswith('/') else '/' + attribute
            apath += attribute
        return apath

    def get_attributes(self,component,attribute: str |None = None,**kwargs)->Any:
        if (path := IDrac.SUBSYSTEM.get(component, None)) is not None:
            if path.startswith('/'):
                apath = self._select_attribute(path,attribute)
                s = self.query(apath)
                return json.loads(s)
            else:
                fn = getattr(self,path.split(':')[0])
                return fn(attribute,**kwargs)


        raise ValueError(f"Invalid {component}, must be one of {','.join(IDrac.SUBSYSTEM.keys())}")

    def set_attributes(self,component,attribute_map:Mapping,**kwargs):
        if (path := IDrac.SUBSYSTEM.get(component, None)) is not None:
            if path.startswith('/'):
                payload = {'Attributes': attribute_map}
                self._check(self.patch(path,payload))
                return
            else:
                fn = getattr(self,path)
                pass

        raise ValueError(f"Invalid {component}, must be one of {','.join(IDrac.SUBSYSTEM.keys())}")

    @cached_property
    def nics(self):
        """NIC names"""
        url = f"/redfish/v1/Chassis/System.Embedded.1/NetworkAdapters/NIC.Integrated.1"
        r = json.loads(self.query(url))
        print(r)
        rval = {}
        r = json.loads(self.query('/redfish/v1/Systems/System.Embedded.1/NetworkInterfaces'))
        for nic_id in  [ m['@odata.id'].split('/')[-1] for m in r['Members']  ]:
            url = f"/redfish/v1/Chassis/System.Embedded.1/NetworkAdapters/{nic_id}/NetworkDeviceFunctions"
            r = json.loads(self.query(url))
            for nic_port in  [m['@odata.id'].split('/')[-1] for m in r['Members']]:
                rval[nic_port] = nic_id
        return rval

    @cached_property
    def network_adapters(self):
        """NIC names"""
        rval = {}
        url = f"/redfish/v1/Chassis/System.Embedded.1/NetworkAdapters/"
        r = json.loads(self.query(url))
        for m in r['Members']:
            for url in m.values():
                r = json.loads(self.query(url))
                data = {k: v for k, v in r.items() if not k.startswith('@')}

                rval[data['Id']] = data

        return rval


    def get_network(self,attribute: str|None,**kwargs):
        if (nic := kwargs.get('nic',None)) is None:
            raise ValueError(f"Keyworkd nic missing")
        if (nic_id := self.nics.get(nic)) is None:
            raise ValueError(f"Invalid nic {nic}, must be one of {','.join(self.nics.keys())}")
        path = f"/redfish/v1/Chassis/System.Embedded.1/NetworkAdapters/{nic_id}/NetworkDeviceFunctions/{nic}" f"/Oem/Dell/DellNetworkAttributes/{nic}"
        apath = self._select_attribute(path, attribute)
        s = self.query(apath)
        return json.loads(s)

    def switch_connections(self):
        rval = []
        path = '/redfish/v1/Systems/System.Embedded.1/NetworkPorts/Oem/Dell/DellSwitchConnections'
        s = self.query(path)
        data = json.loads(s)
        for m in data['Members']:
            sl = m['SwitchConnectionID']
            sp = m['SwitchPortConnectionID']
            if sl != 'No Link':
                iname = m['FQDD']
                rval.append(PortInfo(self.idracname, iname, sl, sp))

        return rval


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
        if query.startswith('/'):
            s = self.redfish_client.get(query)
            self._check(s)
            return s.text
        raise ValueError(f"query{query} must start with /")

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
                    return self._read_reply(200, "get virtual",'')
            return CommandReply(True, "Devices", result)
        # else implicit
        return self._read_reply(200, "get virtual",'')

    def set_next_boot(self, device: str) -> CommandReply:
        """
        Set the next boot device.
        Common values for device:
          - "PXE"
          - "VCD-DVD"
          - "BIOSSetup"
          - "HDD"
          - "Floppy"
          - "None" (to clear override)
        """
        url = self.mgr_path + '/Actions/Oem/EID_674_Manager.ImportSystemConfiguration'
        payload = {
            "ShareParameters": {"Target": "ALL"},
            "ImportBuffer": (
                '<SystemConfiguration>'
                '<Component FQDD="iDRAC.Embedded.1">'
                '<Attribute Name="ServerBoot.1#BootOnce">Enabled</Attribute>'
                f'<Attribute Name="ServerBoot.1#FirstBootDevice">{device}</Attribute>'
                '</Component>'
                '</SystemConfiguration>'
            )
        }
        r = self.redfish_client.post(url, body=payload)
        return self._read_reply(r, 202, f'Boot set to {device}')

    def next_boot_virtual(self) -> CommandReply:
        return self.set_next_boot("VCD-DVD")

    def next_boot_pxe(self) -> CommandReply:
        return self.set_next_boot("PXE")

    def next_boot_bios(self) -> CommandReply:
        return self.set_next_boot("BIOSSetup")

    def _check(self, response, code:int=200):
        """Raise exception if invalid code"""
        if response.status != code:
            raise ValueError(response)

    def update(self, filename):
        """Update firmware by calling Dell provided functions"""
        # update global object
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

    def tsr(self, config):
        nfsip = config['tsr']['nfsip']
        share = config['tsr']['share']

        dellscript = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  '..', 'dell', 'SupportAssistCollectionNetworkShareREDFISH.py')
        if not os.path.isfile(dellscript):
            raise ValueError(f"{dellscript} not found")
        cmd = (sys.executable, dellscript, '-ip', self.idracname, '-x', self.session_key,
               '--export-network', '--sharetype', 'NFS', '--shareip', nfsip, '--sharename', share,
               '--accept', '--data', '0,1')
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

    def set_comment(self,comment):
        """Set idrac comment"""
        url = '/redfish/v1/Managers/iDRAC.Embedded.1/Oem/Dell/DellLCService/Actions/DellLCService.InsertCommentInLCLog'
        payload = {"Comment":comment}
        r = self.redfish_client.post(url,body=payload)
        good =  r.status == 200
        if not good:
            ilogger.warning(r)
        return good


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

    def recent_alerts(self, count: int = 10) -> list[dict]:
        """Get recent SEL log entries, most recent first. Supports iDRAC 8 and 9."""
        for path in (
            '/redfish/v1/Managers/iDRAC.Embedded.1/LogServices/Sel/Entries',  # iDRAC 9
            '/redfish/v1/Managers/iDRAC.Embedded.1/Logs/Sel',                 # iDRAC 8
        ):
            try:
                data = json.loads(self.query(path))
                members = data.get('Members', [])
                ilogger.debug(f"{self.idracname} {path}: {len(members)} member(s)")
                if not members:
                    continue
                # Take the most recent `count` before fetching (avoids fetching the full log)
                entries = []
                for m in members[-count:]:
                    # iDRAC 8 returns link stubs; follow the link to get entry fields
                    if 'Message' not in m and '@odata.id' in m:
                        ilogger.debug(f"{self.idracname} fetching entry {m['@odata.id']}")
                        try:
                            m = json.loads(self.query(m['@odata.id']))
                        except ValueError as e:
                            ilogger.warning(f"{self.idracname} could not fetch {m['@odata.id']}: {e}")
                    ilogger.debug(f"{self.idracname} entry keys: {list(m.keys())}")
                    entries.append(m)
                return list(reversed(entries))
            except ValueError as e:
                ilogger.debug(f"{self.idracname} {path} failed: {e}")
                continue
        ilogger.warning(f"{self.idracname} no log path succeeded")
        return []

    def active_faults(self) -> list[dict]:
        """Get active fault list (what the web UI shows as health causes). Supports iDRAC 8 and 9."""
        for path in (
            '/redfish/v1/Systems/System.Embedded.1/LogServices/FaultList/Entries',  # iDRAC 9
            '/redfish/v1/Managers/iDRAC.Embedded.1/Logs/FaultList',                 # iDRAC 8
        ):
            try:
                data = json.loads(self.query(path))
                members = data.get('Members', [])
                ilogger.debug(f"{self.idracname} {path}: {len(members)} fault(s)")
                if not members:
                    continue
                entries = []
                for m in members:
                    if 'Message' not in m and '@odata.id' in m:
                        try:
                            m = json.loads(self.query(m['@odata.id']))
                        except ValueError as e:
                            ilogger.warning(f"{self.idracname} could not fetch {m['@odata.id']}: {e}")
                    entries.append(m)
                # Discard OK-severity metadata entries (e.g. "Log cleared.")
                faults = [e for e in entries if e.get('Severity', 'OK') != 'OK']
                if not faults:
                    continue
                return faults
            except ValueError as e:
                ilogger.debug(f"{self.idracname} {path} failed: {e}")
                continue
        return []

    def component_health_issues(self) -> list[dict]:
        """Walk subsystem health to find non-OK components (fallback when fault log is unavailable)."""
        issues = []

        def _entry(severity, message):
            return {'Severity': severity, 'Message': message, 'Created': ''}

        # Storage: controllers and drives
        try:
            data = json.loads(self.query('/redfish/v1/Systems/System.Embedded.1/Storage'))
            for ctrl_ref in data.get('Members', []):
                try:
                    ctrl = json.loads(self.query(ctrl_ref['@odata.id']))
                    ctrl_name = ctrl.get('Name', ctrl.get('Id', ctrl_ref['@odata.id']))
                    ctrl_health = ctrl.get('Status', {}).get('Health', 'OK')
                    if ctrl_health and ctrl_health != 'OK':
                        issues.append(_entry(ctrl_health, f"Storage controller {ctrl_name}: health {ctrl_health}"))
                    for drive_ref in ctrl.get('Drives', []):
                        try:
                            drive = json.loads(self.query(drive_ref['@odata.id']))
                            health = drive.get('Status', {}).get('Health', 'OK')
                            if health and health != 'OK':
                                name = drive.get('Name', drive.get('Id', ''))
                                fp = drive.get('FailurePredicted', False)
                                msg = f"Drive {name} on {ctrl_name}: health {health}"
                                if fp:
                                    msg += ' (failure predicted)'
                                issues.append(_entry(health, msg))
                        except ValueError:
                            pass
                except ValueError:
                    pass
        except ValueError:
            pass

        # Simple storage (removable flash, SD cards, USB drives)
        try:
            data = json.loads(self.query('/redfish/v1/Systems/System.Embedded.1/SimpleStorage'))
            for ctrl_ref in data.get('Members', []):
                try:
                    ctrl = json.loads(self.query(ctrl_ref['@odata.id']))
                    ctrl_name = ctrl.get('Name', ctrl.get('Id', ctrl_ref['@odata.id']))
                    for device in ctrl.get('Devices', []):
                        health = device.get('Status', {}).get('Health', 'OK')
                        if health and health != 'OK':
                            name = device.get('Name', '')
                            issues.append(_entry(health, f"Device {name} on {ctrl_name}: health {health}"))
                except ValueError:
                    pass
        except ValueError:
            pass

        # Power supplies
        try:
            data = json.loads(self.query('/redfish/v1/Chassis/System.Embedded.1/Power'))
            for psu in data.get('PowerSupplies', []):
                health = psu.get('Status', {}).get('Health', 'OK')
                if health and health != 'OK':
                    name = psu.get('Name', psu.get('MemberId', ''))
                    issues.append(_entry(health, f"PSU {name}: health {health}"))
        except ValueError:
            pass

        # Fans / thermal
        try:
            data = json.loads(self.query('/redfish/v1/Chassis/System.Embedded.1/Thermal'))
            for fan in data.get('Fans', []):
                health = fan.get('Status', {}).get('Health', 'OK')
                if health and health != 'OK':
                    name = fan.get('Name', fan.get('MemberId', ''))
                    issues.append(_entry(health, f"Fan {name}: health {health}"))
        except ValueError:
            pass

        # Processors
        try:
            data = json.loads(self.query('/redfish/v1/Systems/System.Embedded.1/Processors'))
            for cpu_ref in data.get('Members', []):
                try:
                    cpu = json.loads(self.query(cpu_ref['@odata.id']))
                    health = cpu.get('Status', {}).get('Health', 'OK')
                    if health and health != 'OK':
                        name = cpu.get('Name', cpu.get('Id', ''))
                        issues.append(_entry(health, f"Processor {name}: health {health}"))
                except ValueError:
                    pass
        except ValueError:
            pass

        ilogger.debug(f"{self.idracname} component_health_issues: {len(issues)} issue(s)")
        return issues

    def idrac_passthrough(self,enabled:bool):
        EKEY = 'OS-BMC.1.AdminState'
        value = "Enabled" if enabled else "Disabled"
        attr = self.get_attributes('idrac')
        current = attr['Attributes'][EKEY]
        if current != value:
            payload = {EKEY:value}
            ilogger.info(f"Setting {self.idracname} {payload}")
            self.set_attributes('idrac',payload)
        else:
            ilogger.debug(f"{self.idracname} passthrough already {value}")


