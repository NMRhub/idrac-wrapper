import logging
ilogger = logging.getLogger('iDRAC')
#from idrac.objects import VirtualMedia, JobStatus
from dataclasses import dataclass
DEFAULT_CFG = '/etc/nmrhub.d/idrac.yaml'


@dataclass
class PortInfo:
    host: str
    interface: str
    mac_address: str
    port_id: str


from idrac.idracaccessor import IdracAccessor
