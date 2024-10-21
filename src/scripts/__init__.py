import getpass
import logging
from argparse import ArgumentParser

import keyring
import redfish

from idrac import ilogger


def get_password():
    """Get password from console"""
    return getpass.getpass("Enter password for iDrac:  ")


class PasswordContext:
    """Set keyring password if no exception raised in context"""

    def __init__(self,account):
        self.account = account

    def __enter__(self):
        self.password = keyring.get_password('idrac', self.account)
        need_pass = self.password is None
        if need_pass:
            print(f"Need password for account {self.account}")
            self.password = get_password()
        return  self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            keyring.set_password('idrac', self.account,self.password)

    def password_fn(self):
        return self.password

    def clear(self):
        keyring.delete_password('idrac', self.account)
        print(f"Need password for account {self.account}")
        self.password = get_password()

class IdracSelector:
    """Select iDRACs from commandline or file. Set logging level"""

    def __init__(self,parser:ArgumentParser):
        parser.add_argument('-l', '--loglevel', default='WARN', help="Python logging level")
        parser.add_argument('--redfish-loglevel', default='WARN', help="Loglevel of redfish package")
        systems = parser.add_mutually_exclusive_group(required=True)
        systems.add_argument('--idrac',help='single iDrac to operate on')
        systems.add_argument('--file',help='file with iDrac names')
        self.parser = parser

    @property
    def idracs(self)->list[str]:
        """List of idracs to operate on"""
        args = self.parser.parse_args()
        ilogger.setLevel(getattr(logging,args.loglevel))
        redfish.rest.v1.LOGGER.setLevel(getattr(logging,args.redfish_loglevel))
        if args.idrac:
            return [args.idrac]
        else:
            with open(args.file) as f:
                lines = [r.strip('n') for r in f ]
                return [idr.strip('\n') for idr in lines if not idr.startswith('#') and len(idr)]
