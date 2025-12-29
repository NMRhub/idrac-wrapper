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

"""Set passthrough state"""

def main():
    logging.basicConfig()
    parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    selector = IdracSelector(parser)
    parser.add_argument('enabled',choices=('enabled','disabled'))


    args = parser.parse_args()
    enable = args.enabled == 'enabled'
    for idrac in selector.idracs:
        try:
            with IdracAccessor() as accessor:
                idrac = accessor.connect(idrac, get_password)
                idrac.idrac_passthrough(enable)
                ilogger.info(f"{idrac} passthrough {enable}")
        except Exception as e:
            print(f"{idrac} error {e}",file=sys.stderr)




if __name__ == "__main__":
    main()
