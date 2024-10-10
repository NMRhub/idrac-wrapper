#!/usr/bin/env python3
import argparse
import logging
import socket

import redfish

from idrac.idracaccessor import IdracAccessor,ilogger

from scripts import get_password, PasswordContext

"""Command line driver"""


def main():
    logging.basicConfig()
    parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('-l', '--loglevel', default='WARN', help="Python logging level")
    parser.add_argument('--redfish-loglevel', default='WARN',help="Loglevel of redfish package")
    parser.add_argument('--login', default='root',help="Account to connect to idrac with")
    parser.add_argument('--role',default='Administrator',help="role for new account")
    parser.add_argument('--clear-pw',action='store_true',help="Delete password for --password from keyring")
    parser.add_argument('--show-password',action='store_true',help="Print password to console")
    systems = parser.add_mutually_exclusive_group(required=True)
    systems.add_argument('--idrac',help='single iDrac to operate on')
    systems.add_argument('--file',help='file with iDrac names')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--accounts',action='store_true',help="list accounts")
    group.add_argument('--create',help='create new account')
    group.add_argument('--password',help='Set account password')


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
                idrac = accessor.connect(idrac,get_password)
                if args.accounts:
                    for a in idrac.accounts():
                        print(a)
                if args.create:
                    with PasswordContext(args.create) as pc:
                        if args.clear_pw:
                            pc.clear()
                        slot = idrac.unused_account_slot()
                        idrac.create_account(slot,pc.account,pc.password,args.role)
                if args.password:
                    with PasswordContext(args.password) as pc:
                        if args.clear_pw:
                            pc.clear()
                        idrac.set_password(pc.account,pw := pc.password)
                        if args.show_password:
                            print(f"{idrac} {pc.account} password set to {pw}")
        except Exception as e:
            if ilogger.isEnabledFor(logging.INFO):
                ilogger.exception(f"idrac {idrac}")
            print(f"idrac {idrac} exception {e}")





if __name__ == "__main__":
    main()
