#!/bin/bash 
VERS=3.12 #default version
PYTHON=python$VERS
$PYTHON -m venv $VENV 
./$VENV/bin/pip install -U pip ipython
./$VENV/bin/pip install -e . 
