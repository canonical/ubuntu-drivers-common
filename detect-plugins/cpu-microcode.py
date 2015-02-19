# ubuntu-drivers-common custom detect plugin for x86 CPU microcodes
#
# Author: Dimitri John Ledkov <dimitri.j.ledkov@intel.com>
#
# This plugin detects CPU microcode packages based on pattern matching
# against the "vendor_id" line in /proc/cpuinfo.
#
# To add a new microcode family, simply insert a line into the db
# variable with the following format:
#
# '<Pattern from your cpuinfo output>': '<Name of the driver package>',
#

import logging

db = {
    'GenuineIntel': 'intel-microcode',
    'AuthenticAMD': 'amd64-microcode',
     }

def detect(apt_cache):
    try:
        with open('/proc/cpuinfo') as file:
            for line in file:
                if line.startswith('vendor_id'):
                    cpu = line.split(':')[1].strip()
                    if cpu in db:
                        return [db.get(cpu)]
    except IOError as err:
        logging.debug('could not open /proc/cpuinfo: %s', err)
