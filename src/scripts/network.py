#!/usr/bin/env python3
import argparse
import logging
import sys

import redfish
from pprint import pprint

from idrac import ilogger
from idrac.idracaccessor import IdracAccessor
from idrac.idracclass import IDrac
from scripts import get_password, IdracSelector
from pprint import pprint

"""Hacking version of command line driver"""


def main():
    logging.basicConfig()
    parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    selector = IdracSelector(parser)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--nic')
    group.add_argument('--switch',action='store_true')




    args = parser.parse_args()
    for idrac in selector.idracs:
        try:
            with IdracAccessor() as accessor:
                idrac = accessor.connect(idrac, get_password)
                if args.nic:
                    print(idrac.nics)
                if args.switch:
                    sc = idrac.switch_connections()
                    for pi in sc:
                        print(pi)
                        idrac.set_comment(str(pi))
        except Exception as e:
            print(f"{idrac} error {e}",file=sys.stderr)




if __name__ == "__main__":
    main()
