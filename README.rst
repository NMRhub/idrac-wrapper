idrac-wrapper
=============

This wraps Dell's Redfish API DMTF in a Python library. It supports iDrac 9. 


Basic Usage
-----------

See the manage.py script for example use.

IdracAccessor stores authenticationsession data to a file provided in the constructor. It
defaults to /tmp/idracaccessor{uid}.dat.

Functionality
-------------
The current implementation has a very small subject of iDRAC functionality, but could be 
extended using the example code in https://github.com/dell/iDRAC-Redfish-Scripting. 

Alternative packages
--------------------
The code is based heavily on https://github.com/dell/iDRAC-Redfish-Scripting. We just wrapped
it for our convenience.
