'''Provide a fake sysfs directory for testing.'''

# (C) 2011, 2012 Martin Pitt <martin.pitt@ubuntu.com>
# Adapted from upower's integration test suite (src/linux/integration-test)
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

import tempfile
import shutil
import os

class SysFS:
    def __init__(self):
        '''Construct a fake sysfs tree.

        The tree is initially empty. You can populate it with @add and
        manipulate it with the other methods on this object.
        
        It is kept in a temporary directory which gets removed when the SysFS
        object gets deleted.

        To use this with e. g. libudev, export the SYSFS_PATH environment
        variable to self.sysfs.
        '''
        self.sysfs = tempfile.mkdtemp()

    def __del__(self):
        shutil.rmtree(self.sysfs)

    def add(self, subsystem, name, attributes, properties=None):
        '''Add a new device to the local sysfs tree.

        attributes and (optionally) properties are specified as a normal Python
        dictionary.
        
        Return the device path.
        '''
        dev_dir = os.path.join(self.sysfs, 'devices', name)
        if not os.path.isdir(dev_dir):
            os.makedirs(dev_dir)
        class_dir = os.path.join(self.sysfs, 'class', subsystem)
        if not os.path.isdir(class_dir):
            os.makedirs(class_dir)

        os.symlink(os.path.join('..', '..', 'devices', name), os.path.join(class_dir, name))
        os.symlink(os.path.join('..', '..', 'class', subsystem), os.path.join(dev_dir, 'subsystem'))

        attributes['uevent'] = self._props_to_str(properties)

        for a, v in attributes.items():
            self.set_attribute(dev_dir, a, v)

        return dev_dir

    def get_attribute(self, devpath, name):
        '''Get device attribute'''

        with open(os.path.join(devpath, name), 'r') as f:
            return f.read()

    def set_attribute(self, devpath, name, value):
        '''Set device attribute'''

        with open(os.path.join(devpath, name), 'w') as f:
            f.write(value)

    def set_property(self, devpath, name, value):
        '''Set device udev property'''

        prop_str = self.get_attribute(devpath, 'uevent')
        props = {}
        for l in prop_str.splitlines():
            (k, v) = l.split('=')
            props[k] = v.rstrip()

        props[name] = value

        self.set_attribute(devpath, 'uevent', self._props_to_str(props))

    @classmethod
    def _props_to_str(cls, properties):
        '''Convert a properties dictionary to uevent text representation.'''

        prop_str = ''
        if properties:
            for k, v in properties.items():
                prop_str += '%s=%s\n' % (k, v)
        return prop_str
