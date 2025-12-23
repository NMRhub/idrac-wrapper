#!/usr/bin/env python3
import argparse
import datetime
import json
import logging
import time

import redfish
import yaml

from idrac import ilogger, DEFAULT_CFG
from idrac.idracaccessor import IdracAccessor
from idrac.idracclass import IDrac
from scripts import get_password
from pprint import pprint

"""Command line driver"""

def get(idrac:IDrac,attribute:str)->None:
    r = idrac.get_attributes(attribute)
    pprint(r)

def read_config(file):
    with open(file) as f:
        return yaml.safe_load(f)

def wait_for_power(idrac:IDrac,state:str,seconds:int)-> bool:
    deadline = (start := datetime.datetime.now()) + datetime.timedelta(seconds=seconds)
    print(f"Waiting up to {seconds} seconds for power to be {state}")
    counter = 0
    while (s := idrac.summary).power != state:
        now = datetime.datetime.now()
        if now > deadline:
            print(f"Timed out, state is {s}")
            return False
        if counter % 5 == 0:
            elasped = datetime.datetime.now() - start
            print(f"{s} {elasped.total_seconds()}")
            counter += 1
        time.sleep(1)
    return True

def reboot(idrac):
    cr =idrac.turn_off()
    print(cr.msg)
    if not wait_for_power(idrac, 'Off',60):
        cr = idrac.force_off()
        print(cr.msg)
        if not wait_for_power(idrac, 'Off',60):
            raise ValueError("Force off failed")
    cr = idrac.turn_on()
    print(cr.msg)
    if not wait_for_power(idrac, 'On',60):
        raise ValueError("Power on failed")


def main():
    logging.basicConfig()
    parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('-l', '--loglevel', default='WARN', help="Python logging level")
    parser.add_argument('--redfish-loglevel', default='WARN',help="Loglevel of redfish package")
    parser.add_argument('idrac',help="iDrac to connect to")
    parser.add_argument('--onlyip',action='store_true',help="Don't show idrac hostname, just ip")
    parser.add_argument('--config',default=DEFAULT_CFG,help='config file, if required')
    parser.add_argument('--wait',type=int,default=0,help='Wait in seconds for action')

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--summary',action='store_true',help="Show quick summary")
    group.add_argument('--dump',action='store_true',help="Dump available data")
    group.add_argument('--metadata',action='store_true',help="Show XML metadata")
    group.add_argument('--off',action='store_true',help="TURN system off")
    group.add_argument('--force-off',action='store_true',help="TURN system off")
    group.add_argument('--on',action='store_true',help="TURN system on")
    group.add_argument('--query',help="redfish query")
    group.add_argument('--tasks',action='store_true',help="Get tasks")
    group.add_argument('--get-virtual',action='store_true',help="get Virtual CD/DVD/ISO info")
    group.add_argument('--mount-virtual',help="Mount Virtual CD/DVD/ISO on url")
    group.add_argument('--eject-virtual',action='store_true',help="Disconnect Virtual CD/DVD/ISO")
    group.add_argument('--next-boot-virtual',action='store_true',help="Make next boot off Virtual CD/DVD/ISO")
    group.add_argument('--pxe-boot',action='store_true',help="Make next boot PXE")
    group.add_argument('--pxe-now',action='store_true',help="PXE reboot now")
    group.add_argument('--update',help="Apply update")
    group.add_argument('--tsr',action='store_true',help="Generate TSR to network share. Requires config")
    group.add_argument('--setarchive',help="Set NFS archive directory (ip:export)")
    group.add_argument('--last',help="Fetch last collection to NFS (ip:export)")
    group.add_argument('--get',nargs='?',help = "get attributes")
    group.add_argument('--reboot',action='store_true',help="reboot sequence via power ops")
    group.add_argument('--schema',action='store_true',help="Dump schema")


    args = parser.parse_args()
    if args.onlyip:
        IDrac.Summary.only_ip = True
    ilogger.setLevel(getattr(logging,args.loglevel))
    redfish.rest.v1.LOGGER.setLevel(getattr(logging,args.redfish_loglevel))
    with IdracAccessor() as accessor:
        cr = None
        powerWait = None
        idrac = accessor.connect(args.idrac, get_password)
        if args.off:
            cr =idrac.turn_off()
            print(cr.msg)
            powerWait = 'Off'
        if args.on:
            cr = idrac.turn_on()
            print(cr.msg)
            powerWait = 'On'
        if args.force_off:
            cr = idrac.force_off()
            print(cr.msg)
            powerWait = 'Off'
        if args.summary:
            print(idrac.summary)
        if args.dump:
            pprint(idrac._system)
        if args.metadata:
            print(idrac.xml_metdata)
        if args.query:
            j = json.loads(idrac.query(args.query))
            print(json.dumps(j,indent=2,sort_keys=True))
        if args.get_virtual:
            cr = idrac.get_virtual()
            if cr.succeeded:
                for d in cr.results:
                    print(d)
        if args.mount_virtual:
            cr =idrac.mount_virtual(args.mount_virtual)
            print(cr.msg)
        if args.eject_virtual:
            cr = idrac.eject_virtual()
            print(cr.msg)
        if args.next_boot_virtual:
            cr = idrac.next_boot_virtual()
        if args.pxe_boot:
            cr = idrac.next_boot_pxe()
        if args.pxe_now:
            cr = idrac.next_boot_pxe()
            reboot(idrac)
        if args.update:
            idrac.update(args.update)
        if args.tsr:
            idrac.tsr(read_config(args.config))
        if args.wait:
            deadline = (start := datetime.datetime.now()) + datetime.timedelta(seconds=args.wait)
            if cr is not None and cr.job is not None and cr.job != 0:
                print(f'{cr.msg} {cr.job}\nWaiting for completion')
                idrac.wait_for(cr.job)
            else:
                print("Wait not applicable for specified action")
            if powerWait is not None:
                wait_for_power(idrac,powerWait,args.wait)
        if args.reboot:
            reboot(idrac)
        if args.schema:
            print(idrac.schemas)


if __name__ == "__main__":
    main()
