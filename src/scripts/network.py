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

"""Network operations"""


def main():
    logging.basicConfig()
    parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    selector = IdracSelector(parser)
    parser.add_argument('--filter',nargs=2,help="Filter selected attribute")
    parser.add_argument('--print-only',action='store_false',help="If not set, an idrac comment is added for switch connections")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--nic',action='store_true')
    group.add_argument('--adapter',action='store_true')
    group.add_argument('--switch',action='store_true',help="Label network switch information in iDRAC")




    args = parser.parse_args()
    add_comment = args.print_only
    for idrac in selector.idracs:
        try:
            with IdracAccessor() as accessor:
                idrac = accessor.connect(idrac, get_password)
                if args.filter:
                    key, value = args.filter
                    v = getattr(idrac,key)
                    if value not in v:
                        ilogger.debug(f"skipping {idrac.idracname} filter {key} {value} not in  {v}")
                        continue
                if args.adapter:
                    for dev, info in idrac.network_adapters.items():
                        if (m := info.get('Model')) is not None and '710' in m:
                            dname = dev.split('/')[-1]
                            print(f"{idrac.idracname} {dname}")
                            sc = idrac.switch_connections()
                            for pi in sc:
                                print(f"\t{pi}")
                if args.nic:
                    print(idrac.nics)
                if args.switch:
                    try:
                        sc = idrac.switch_connections()
                        summary = idrac.summary
                        for pi in sc:
                            print(f"{pi.host},{pi.interface},{pi.mac_address},{pi.port_id},{summary.hostname}")
                            if add_comment:
                                idrac.set_comment(str(pi))
                    except Exception as e:
                        print(f"{idrac.idracname} error {e}", file=sys.stderr)
        except Exception as e:
            print(f"{idrac} error {e}",file=sys.stderr)




if __name__ == "__main__":
    main()
