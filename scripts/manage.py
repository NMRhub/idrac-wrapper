#!/usr/bin/env python3
import argparse
import logging
import redfish
from pprint import pprint


from idrac.idracaccessor import IdracAccessor,ilogger
from scripts import get_password

"""Command line driver"""


def main():
    logging.basicConfig()
    parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('-l', '--loglevel', default='WARN', help="Python logging level")
    parser.add_argument('--redfish-loglevel', default='WARN',help="Loglevel of redfish package")
    parser.add_argument('idrac',help="iDract to connec to")
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
    group.add_argument('--update',help="Apply update")
    group.add_argument('--tsr',action='store_true',help="Generate TSR")


    args = parser.parse_args()
    ilogger.setLevel(getattr(logging,args.loglevel))
    redfish.rest.v1.LOGGER.setLevel(getattr(logging,args.redfish_loglevel))
    with IdracAccessor() as accessor:
        idrac = accessor.connect(args.idrac, get_password)
        if args.off:
            cr =idrac.turn_off()
            print(cr.msg)
        if args.on:
            cr = idrac.turn_on()
            print(cr.msg)
        if args.force_off:
            cr = idrac.force_off()
            print(cr.msg)
        if args.summary:
            print(idrac.summary)
        if args.dump:
            pprint(idrac._system)
        if args.metadata:
            print(idrac.xml_metdata)
        if args.query:
            print(idrac.query(args.query))
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
            print(f'{cr.msg} {cr.job}\nWaiting for completion')
            idrac.wait_for(cr.job)
        if args.pxe_boot:
            cr = idrac.next_boot_pxe()
            print(f'{cr.msg} {cr.job}\nWaiting for completion')
            idrac.wait_for(cr.job)
        if args.update:
            idrac.update(args.update)
        if args.tsr:
            idrac.tsr()



if __name__ == "__main__":
    main()
