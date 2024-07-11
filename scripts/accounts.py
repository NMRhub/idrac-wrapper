#!/usr/bin/env python3
import argparse
import getpass
import logging
import redfish
from pprint import pprint


from idrac.idracaccessor import IdracAccessor,ilogger
import keyring

from scripts import get_password

"""Command line driver"""


def main():
    logging.basicConfig()
    parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('-l', '--loglevel', default='WARN', help="Python logging level")
    parser.add_argument('--redfish-loglevel', default='WARN',help="Loglevel of redfish package")
    parser.add_argument('--role',default='Administrator',help="role for new account")
    systems = parser.add_mutually_exclusive_group(required=True)
    systems.add_argument('--idrac',help='single iDrac to operate on')
    systems.add_argument('--file',help='file with iDrac names')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--accounts',action='store_true',help="list accounts")
    group.add_argument('--create',help='create new account')


    args = parser.parse_args()
    ilogger.setLevel(getattr(logging,args.loglevel))
    redfish.rest.v1.LOGGER.setLevel(getattr(logging,args.redfish_loglevel))
    if args.idrac:
        idracs = list((args.idrac,))
    else:
        with open(args.file) as f:
            lines = [r.strip('n') for r in f ]
            idracs = [idr for idr in lines if not idr.startswith('#') and len(idr)]
    for idrac in idracs:
        with IdracAccessor() as accessor:
            idrac = accessor.connect(idrac,get_password)
            if args.accounts:
                for a in idrac.accounts():
                    print(a)
            if args.create:
                pw = keyring.get_password('idrac',args.create)
                need_pass =  pw is None
                if need_pass:
                    print(f"Need password for account {args.create}")
                    pw = get_password()
                slot = idrac.unused_account_slot()
                idrac.create_account(slot,args.create,pw,args.role)
                keyring.set_password('idrac',args.create,pw)





if __name__ == "__main__":
    main()
