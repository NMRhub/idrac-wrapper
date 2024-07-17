#!/bin/bash
ORIGIN=$(dirname $(readlink -f $0))
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
./venv/bin/python setup.py install
