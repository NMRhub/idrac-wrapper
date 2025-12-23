#!/usr/bin/env python3
import argparse
import collections
import logging
import queue
import socket
import threading
import time

import redfish

from idrac.idracaccessor import IdracAccessor,ilogger

from scripts import get_password, PasswordContext, IdracSelector

"""Command line driver"""

results = queue.Queue()

def get_summary(name):
    try:
        with IdracAccessor() as accessor:
            idrac = accessor.connect(name, get_password)
            results.put(idrac.summary)
    except Exception:
        ilogger.exception(f"{name} summary")

def show():
    try:
        while True:
            s = results.get(timeout=1)
            print(s)
    except queue.Empty:
        return

def main():
    logging.basicConfig()
    parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    selector = IdracSelector(parser)


    args = parser.parse_args()
    threads = set()
    for idrac_name in selector.idracs:
        threads.add(t := threading.Thread(target=get_summary,args=(idrac_name,),name=idrac_name))
        t.start()
    while True:
        show()
        complete = []
        t: threading.Thread
        for t in threads:
            if not t.is_alive():
                complete.append(t)
        for t in complete:
            threads.remove(t)
        if len(threads) == 0:
            return
        time.sleep(1)





if __name__ == "__main__":
    main()
