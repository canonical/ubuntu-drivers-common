'''Provide a fake package archive for testing.'''

# (C) 2012 Martin Pitt <martin.pitt@ubuntu.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

import tempfile
import shutil
import os
import subprocess
import atexit

class Archive:
    def __init__(self):
        '''Construct a local package test archive.

        The archive is initially empty. You can create new packages with
        create_deb(). self.path contains the path of the archive, and
        self.apt_source provides an apt source "deb" line.
        
        It is kept in a temporary directory which gets removed when the Archive
        object gets deleted.
        '''
        self.path = tempfile.mkdtemp()
        atexit.register(shutil.rmtree, self.path)
        self.apt_source = 'deb file://%s /' % self.path

    def create_deb(self, name, version='1', architecture='all',
            dependencies={}, description='test package', extra_tags={},
            files={}, update_index=True):
        '''Build a deb package and add it to the archive.

        The only mandatory argument is the package name. You can additionall
        specify the package version (default '1'), architecture (default
        'all'), a dictionary with dependencies (empty by default; for example
        {'Depends': 'foo, bar', 'Conflicts: baz'}, a short description
        (default: 'test package'), and arbitrary extra tags.

        By default the package is empty. It can get files by specifying a path ->
        contents dictionary in 'files'. Paths must be relative. Example: 
          files={'etc/foo.conf': 'enable=true'}

        The newly created deb automatically gets added to the "Packages" index,
        unless update_index is False.

        Return the path to the newly created deb package, in case you only need
        the deb itself, not the archive.
        '''
        d = tempfile.mkdtemp()
        os.mkdir(os.path.join(d, 'DEBIAN'))
        with open(os.path.join(d, 'DEBIAN', 'control'), 'w') as f:
            f.write('''Package: %s
Maintainer: Test User <test@example.com>
Version: %s
Priority: optional
Section: devel
Architecture: %s
''' % (name, version, architecture))

            for k, v in dependencies.items():
                f.write('%s: %s\n' % (k, v))

            f.write('''Description: %s
 Test dummy package.
''' % description)

            for k, v in extra_tags.items():
                f.write('%s: %s\n' % (k, v))

        for path, contents in files.items():
            if type(contents) == bytes:
                mode = 'wb'
            else:
                mode = 'w'
            pathdir = os.path.join(d, os.path.dirname(path))
            if not os.path.isdir(pathdir):
                os.makedirs(pathdir)
            with open(os.path.join(d, path), mode) as f:
                f.write(contents)

        debpath = os.path.join(self.path, '%s_%s_%s.deb' % (name, version, architecture))
        dpkg = subprocess.Popen(['dpkg', '-b', d, debpath],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        dpkg.communicate()
        assert dpkg.returncode == 0

        shutil.rmtree(d)
        assert os.path.exists(debpath)

        if update_index:
            self.update_index()

        return debpath

    def update_index(self):
        '''Update the "Packages" index.

        This usually gets done automatically by create_deb(), but needs to be
        done if you manually copy debs into the archive or call create_deb with
        update_index==False.
        '''
        old_cwd = os.getcwd()
        try:
            os.chdir(self.path)
            with open('Packages', 'w') as f:
                subprocess.check_call(['apt-ftparchive', 'packages', '.'], stdout=f)
        finally:
            os.chdir(old_cwd)

#a = Archive()
#a.create_deb('vanilla')
#a.create_deb('chocolate', dependencies={'Depends': 'foo'}, 
#    extra_tags={'Modaliases': 'pci-1'},
#    files={'usr/share/doc/chocolate/README': 'hello'})
#print(a.apt_source)
#subprocess.call(['bash', '-i'], cwd=a.path)
