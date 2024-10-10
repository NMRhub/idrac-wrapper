#!/usr/bin/env python3
import argparse
import getpass
import logging
import socket

import redfish
from pprint import pprint


from idrac.idracaccessor import IdracAccessor,ilogger
import keyring

from scripts import get_password, PasswordContext

"""Command line driver"""



def main():
    logging.basicConfig()
    parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('-l', '--loglevel', default='WARN', help="Python logging level")
    parser.add_argument('--redfish-loglevel', default='WARN',help="Loglevel of redfish package")
    parser.add_argument('--login', default='root',help="Account to connect to idrac with")
    parser.add_argument('--show-password',action='store_true',help="Print password to console")
    systems = parser.add_mutually_exclusive_group(required=True)
    systems.add_argument('--idrac',help='single iDrac to operate on')
    systems.add_argument('--file',help='file with iDrac names')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--setarchive',help="Set NFS archive directory (ip:export)")
    group.add_argument('--last',help="Fetch last collection to NFS (ip:export)")


    args = parser.parse_args()
    ilogger.setLevel(getattr(logging,args.loglevel))
    redfish.rest.v1.LOGGER.setLevel(getattr(logging,args.redfish_loglevel))
    if args.idrac:
        idracs = list((args.idrac,))
    else:
        with open(args.file) as f:
            lines = [r.strip('n') for r in f ]
            idracs = [idr.strip('\n') for idr in lines if not idr.startswith('#') and len(idr)]
    for idrac in idracs:
        try:
            ip = socket.gethostbyname(idrac)
            print(f'IDRAC: {idrac} {ip}')
            with IdracAccessor(login=args.login) as accessor:
                with PasswordContext(args.login) as pc:
                    idrac = accessor.connect(idrac,pc.password_fn)
                    if args.setarchive:
                        idrac.set_archive_dir(args.setarchive)
                    if args.last:
                        idrac.get_last_collection(args.last)
        except Exception as e:
            if ilogger.isEnabledFor(logging.INFO):
                ilogger.exception(f"idrac {idrac}")
            print(f"idrac {idrac} exception {e}")





if __name__ == "__main__":
    main()
