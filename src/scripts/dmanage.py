#!/usr/bin/env python3
import argparse
import logging
import redfish
from pprint import pprint

from idrac import ilogger
from idrac.idracaccessor import IdracAccessor
from idrac.idracclass import IDrac
from scripts import get_password
from pprint import pprint

"""Hacking version of command line driver"""


def main():
    logging.basicConfig()
    parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('-l', '--loglevel', default='WARN', help="Python logging level")
    parser.add_argument('--redfish-loglevel', default='WARN',help="Loglevel of redfish package")
    parser.add_argument('idrac',help="iDrac to connect to")
    parser.add_argument('--onlyip',action='store_true',help="Don't show idrac hostname, just ip")



    args = parser.parse_args()
    if args.onlyip:
        IDrac.Summary.only_ip = True
    ilogger.setLevel(getattr(logging,args.loglevel))
    redfish.rest.v1.LOGGER.setLevel(getattr(logging,args.redfish_loglevel))
    with IdracAccessor() as accessor:
        idrac = accessor.connect(args.idrac, get_password)
        idrac.nics
#        r = idrac.get_attributes()
        #r = idrac.get_attributes('/WebServer.1.Enable')
#        r = idrac.get_attributes('idrac','WebServer.1.Enable')
        #r = idrac.get_attributes('bios')
        #r = idrac.get_attributes('lifecycle')
        r = idrac.get_attributes('network',nic='NIC.Integrated.1-1-1')
        pprint(r)
        r = idrac.get_attributes('network',nic='NIC.Embedded.1-1-1')
        pprint(r)




if __name__ == "__main__":
    main()
