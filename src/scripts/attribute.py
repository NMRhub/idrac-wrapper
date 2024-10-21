#!/usr/bin/env python3
import argparse
import logging
import socket
import sys
from pprint import pprint
from idrac.idracclass import IDrac

import redfish

import idrac.idracclass
from idrac.idracaccessor import IdracAccessor,ilogger

from scripts import get_password, PasswordContext, IdracSelector

"""Command line driver"""


def main():
    logging.basicConfig()
    parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('subsys',choices=sorted(IDrac.SUBSYSTEM.keys()),help="system to query")
    parser.add_argument('--nic',help="NIC port for network queries")
    selector = IdracSelector(parser)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--get',help="Get racadm attributes")
    group.add_argument('--all',action='store_true',help="Get racadm attributes")
    group.add_argument('--set',action='append',help="Set atttribute. attribute=value")


    args = parser.parse_args()
    for idrac in selector.idracs:
        try:
            ip = socket.gethostbyname(idrac)
            print(f'IDRAC: {idrac} {ip}')
            with IdracAccessor() as accessor:
                idrac = accessor.connect(idrac,get_password)
                if args.subsys == 'network' and args.nic is None:
                    print("network requires --nic. Options are:",file=sys.stderr)
                    for n in idrac.nics.keys():
                        print(f"\t{n}",file=sys.stderr)
                    sys.exit(1)
                if args.all:
                    r = idrac.get_attributes(args.subsys,nic=args.nic)
                    pprint(r)
                if args.get:
                    r = idrac.get_attributes(args.subsys,args.get,nic=args.nic)
                    pprint(r)
                if args.set:
                    payload = {}
                    for a in args.set:
                        pair = a.split('=')
                        if len(pair) == 2:
                            payload[pair[0]] = pair[1]
                        else:
                            print(f"--set must contain single = sign, invalid {a}",file=sys.stderr)
                            sys.exit(1)
                    idrac.set_attributes(args.subsys, payload, nic=args.nic)
        except Exception as e:
            if ilogger.isEnabledFor(logging.INFO):
                ilogger.exception(f"idrac {idrac}")
            print(f"idrac {idrac} exception {e}")





if __name__ == "__main__":
    main()
