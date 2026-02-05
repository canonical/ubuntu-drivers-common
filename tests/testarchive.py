"""Provide a fake package archive for testing."""

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
        """Construct a local package test archive.

        The archive is initially empty. You can create new packages with
        create_deb(). self.path contains the path of the archive, and
        self.apt_source provides an apt source "deb" line.

        It is kept in a temporary directory which gets removed when the Archive
        object gets deleted.
        """
        self.path = tempfile.mkdtemp()
        self.dist = "devel"
        self.components = ["main", "universe", "restricted", "multiverse"]
        self.archs = ["amd64", "i386", "arm64", "armhf", "ppc64el", "s390x"]

        atexit.register(shutil.rmtree, self.path)

        # Local repository is not signed so trusted is required
        self.apt_source_pattern = "deb [trusted=yes] file://%s %s %s"
        self.apt_source = self.apt_source_pattern % (
            self.path,
            self.dist,
            " ".join(self.components),
        )

        # Configuration file for apt-ftparchive to generate archive indices
        # For simplification Suite and Codename are the same and we nly support
        # one arch. This can be further extended to support other archs if the
        # testsuite requires it
        self.aptftp_conf = os.path.join(self.path, "aptftp.conf")
        with open(self.aptftp_conf, "w") as f:
            f.write(
                """
APT::FTPArchive::Release {{
Origin "Ubuntu";
Label "Ubuntu";
Suite "{suite}";
Codename "{codename}";
Architectures "{archs}";
Components "{components}";
Description "Test Repository";
}};
""".format(
                    suite=self.dist,
                    codename=self.dist,
                    archs=" ".join(self.archs),
                    components=" ".join(self.components),
                )
            )

        self.aptftp_generate_conf = os.path.join(self.path, "aptftpgenerate.conf")
        with open(self.aptftp_generate_conf, "w") as f:
            f.write(
                """
Dir::ArchiveDir ".";
Dir::CacheDir ".";
TreeDefault::Directory "pool/$(SECTION)/";
TreeDefault::SrcDirectory "pool/$(SECTION)/";
Default::Packages::Extensions ".deb";
Default::Packages::Compress ". gzip bzip2";
Default::Sources::Compress ". gzip bzip2";
Default::Contents::Compress "gzip bzip2";

Tree "dists/{dist}" {{
  Sections "{components}";
  Architectures "{archs}";
}};
""".format(
                    dist=self.dist,
                    archs=" ".join(self.archs),
                    components=" ".join(self.components),
                )
            )

            for arch in self.archs:
                for component in self.components:
                    f.write(
                        """
BinDirectory "dists/{dist}/{component}/binary-{arch}" {{
  Packages "dists/{dist}/{component}/binary-{arch}/Packages";
  Contents "dists/{dist}/Contents-{arch}";
}};
""".format(
                            dist=self.dist, arch=arch, component=component
                        )
                    )

    def create_deb(
        self,
        name,
        version="1",
        architecture="all",
        dependencies={},
        description="test package",
        extra_tags={},
        files={},
        component="main",
        srcpkg=None,
        update_index=True,
    ):
        """Build a deb package and add it to the archive.

        The only mandatory argument is the package name. You can additionally
        specify the package version (default '1'), architecture (default
        'all'), a dictionary with dependencies (empty by default; for example
        {'Depends': 'foo, bar', 'Conflicts: baz'}, a short description
        (default: 'test package'), and arbitrary extra tags.

        By default the package is empty. It can get files by specifying a
        path -> contents dictionary in 'files'. Paths must be relative.
        Example: files={'etc/foo.conf': 'enable=true'}

        The newly created deb automatically gets added to the "Packages" index,
        unless update_index is False.

        Return the path to the newly created deb package, in case you only need
        the deb itself, not the archive.
        """
        d = tempfile.mkdtemp()
        os.mkdir(os.path.join(d, "DEBIAN"))
        with open(os.path.join(d, "DEBIAN", "control"), "w") as f:
            f.write(
                """Package: %s
Maintainer: Test User <test@example.com>
Version: %s
Priority: optional
Section: devel
Architecture: %s
"""
                % (name, version, architecture)
            )

            for k, v in dependencies.items():
                f.write("%s: %s\n" % (k, v))

            f.write(
                """Description: %s
 Test dummy package.
"""
                % description
            )

            for k, v in extra_tags.items():
                f.write("%s: %s\n" % (k, v))

        for path, contents in files.items():
            if isinstance(contents, bytes):
                mode = "wb"
            else:
                mode = "w"
            pathdir = os.path.join(d, os.path.dirname(path))
            if not os.path.isdir(pathdir):
                os.makedirs(pathdir)
            with open(os.path.join(d, path), mode) as f:
                f.write(contents)

        if srcpkg is None:
            srcpkg = name
        if srcpkg.startswith("lib"):
            prefix = srcpkg[:4]
        else:
            prefix = srcpkg[0]
        dir = os.path.join(self.path, "pool", component, prefix, srcpkg)
        if not os.path.isdir(dir):
            os.makedirs(dir)

        debpath = os.path.join(dir, "%s_%s_%s.deb" % (name, version, architecture))
        subprocess.check_call(
            ["dpkg", "-b", d, debpath], stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )

        shutil.rmtree(d)
        assert os.path.exists(debpath)

        if update_index:
            self.update_index()

        return debpath

    def update_index(self):
        """Update the "Packages" index.

        This usually gets done automatically by create_deb(), but needs to be
        done if you manually copy debs into the archive or call create_deb with
        update_index==False.
        """
        old_cwd = os.getcwd()
        try:
            os.chdir(self.path)
            devnull = open(os.devnull, "w")  # Make apt-ftparchive quiet
            dists_dir = os.path.join(self.path, "dists")

            # Completely recreates the dist directory to ensure there is no
            # leftover from a previous test.
            if os.path.isdir(dists_dir):
                shutil.rmtree(dists_dir)
            for arch in self.archs:
                for component in self.components:
                    os.makedirs(
                        os.path.join(
                            dists_dir, self.dist, component, "binary-%s" % arch
                        )
                    )

            subprocess.check_call(
                [
                    "apt-ftparchive",
                    "generate",
                    "-c",
                    self.aptftp_conf,
                    self.aptftp_generate_conf,
                ],
                stderr=devnull,
            )

            with open(os.path.join(dists_dir, self.dist, "Release"), "w") as f:
                subprocess.check_call(
                    [
                        "apt-ftparchive",
                        "release",
                        "-c",
                        self.aptftp_conf,
                        os.path.join(dists_dir, self.dist),
                    ],
                    stdout=f,
                    stderr=devnull,
                )

            # This is still required by the aptdaemon test structure
            with open("Packages", "w") as f:
                subprocess.check_call(
                    ["apt-ftparchive", "packages", "."], stdout=f, stderr=devnull
                )

        finally:
            os.chdir(old_cwd)
            devnull.close()


# a = Archive()
# a.create_deb('vanilla')
# a.create_deb('chocolate', dependencies={'Depends': 'foo'},
#     extra_tags={'Modaliases': 'pci-1'},
#     files={'usr/share/doc/chocolate/README': 'hello'})
# print(a.apt_source)
# subprocess.call(['bash', '-i'], cwd=a.path)
