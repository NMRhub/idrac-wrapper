#!/usr/bin/env python3.6
from setuptools import setup
with open("README.rst", "r") as fh:
    readme_long_description = fh.read()

setup(name='idrac-wrapper',
      version='1.4',
      description='iDRAC redfish library wrapper',
      url='https://github.com/NMRhub/idrac-wrapper',
      long_description_content_type='text/x-rst',
      long_description = readme_long_description,
      maintainer='Gerard Weatherby',
      install_requires=['requests','redfish','keyring'],
      maintainer_email='gweatherby@uchc.edu',
      packages=[
          'idrac','scripts','dell'
      ],
      entry_points={
          'console_scripts':
              [
                  'idrac = scripts.manage:main',
                  'accounts = scripts.accounts:main',
              ]
      }
)
