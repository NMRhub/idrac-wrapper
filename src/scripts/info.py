#!/usr/bin/env python3
import argparse
import json
import logging
import queue
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from threading import Thread
from typing import Any

import yaml

from idrac.idracaccessor import IdracAccessor, ilogger
from scripts import get_password, IdracSelector

class DotAccess:

    @staticmethod
    def _safe_key(k: str) -> str:
        k = re.sub(r"[^0-9a-zA-Z_]", "_", k)
        return k if k.isidentifier() else f"_{k}"

    def __init__(self, d: dict):
        self._data = {}
        for k, v in d.items():
            sk = self._safe_key(k)
            val = self._wrap(v)
            self._data[sk] = val
            setattr(self, sk, val)

    def _wrap(self, v):
        if isinstance(v, dict): return DotAccess(v)
        if isinstance(v, list): return [self._wrap(i) for i in v]
        return v

    def __getattr__(self, name):
        if "." not in name: raise AttributeError(name)
        obj = self
        for part in name.split("."):
            obj = getattr(obj, part)
        return obj

    def raw(self) -> dict:
        return self._data


@dataclass
class RawData:
    idrac: str
    _data: Any

    @property
    def data(self):
        return json.loads(self._data)


class InfoFromCheatsheet:

    def __init__(self, cfile):
        self.file_name = cfile
        with open(cfile) as f:
            self.qdata = yaml.safe_load(f)
        self.data_queue = queue.Queue()
        self.threads: list[Thread] = []

    def query(self, selector: IdracSelector, request):
        if (cd := self.qdata.get(request, None)) is None:
            print(f"Query {request} not found. Current queries are:  ")
            for k in self.qdata.keys():
                print(f"\t{k}")
            return
        redfish_path = cd['redfish path']
        self.result_path = cd['result path']

        ilogger.info(f"query {redfish_path}")
        for idrac in (idrac_list := selector.idracs):
            ithread = Thread(target=self._threaded_q, args=(idrac, redfish_path))
            ithread.name = idrac
            ithread.start()
            self.threads.append(ithread)

        for t in self.threads:
            t.join(timeout=60)
        dout = False
        if ilogger.isEnabledFor(logging.DEBUG):
            dout = True
            debug_path = Path(tempfile.gettempdir()) / 'idrac-info'
            debug_path.mkdir(exist_ok=True)

        collector = {}
        for _ in range(len(self.threads)):
            rd: RawData
            rd = self.data_queue.get(timeout=60)
            ilogger.info(f"{rd.idrac} published")
            if dout:
                # noinspection PyUnboundLocalVariable
                with open(df := debug_path / rd.idrac, 'w') as f:
                    print(json.dumps(rd.data, indent=2), file=f)
                ilogger.debug(f"Dumped {df.as_posix()}")
            da = DotAccess(rd.data)
            if (value := getattr(da, self.result_path, None)) is not None:
                collector[rd.idrac] = value
            else:
                ilogger.warning(f"result {self.result_path} not found for {rd.idrac}")

        for name in idrac_list:
            if (value := collector.get(name,None)) is not None:
                print(f"{name} {request} {self.result_path}: {value}")
            else:
                ilogger.warning(f"No result for {name}")


    def _threaded_q(self, name, path):
        with IdracAccessor() as accessor:
            idrac = accessor.connect(name, get_password)
            q = idrac.query(path)
            self.data_queue.put(RawData(name, q))


def main():
    logging.basicConfig()
    parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('cheatsheet', help="YAML file with query info")
    parser.add_argument('query', help="Query from cheatsheet to use")
    selector = IdracSelector(parser)

    args = parser.parse_args()
    ifc = InfoFromCheatsheet(args.cheatsheet)
    ifc.query(selector, args.query)


if __name__ == "__main__":
    main()
