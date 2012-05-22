import logging
import fnmatch
import re

from packagekit import enums
import apt

valid_modalias_re = re.compile('^[a-z0-9]+:\S+$')
system_architecture = apt.apt_pkg.get_architectures()[0]

def what_provides_modalias(apt_cache, provides_type, search):
    if provides_type not in (enums.PROVIDES_MODALIAS, enums.PROVIDES_ANY):
        raise NotImplementedError('cannot handle type ' + str(provides_type))

    if not valid_modalias_re.match(search):
        if provides_type != enums.PROVIDES_ANY:
            raise ValueError('The search term is invalid: %s' % search)
        else:
            return []

    result = []
    for package in apt_cache:
        # skip foreign architectures, we usually only want native
        # driver packages
        if (not package.candidate or
            package.candidate.architecture not in ('all', system_architecture)):
            continue

        try:
            m = package.candidate.record['Modaliases']
        except (KeyError, AttributeError):
            continue

        try:
            pkg_matches = False
            for part in m.split(')'):
                part = part.strip(', ')
                if not part:
                    continue
                module, lst = part.split('(')
                for alias in lst.split(','):
                    alias = alias.strip()
                    if fnmatch.fnmatch(search, alias):
                        result.append(package)
                        pkg_matches = True
                        break
                if pkg_matches:
                    break
        except ValueError:
            logging.error('Package %s has invalid modalias header: %s' % (
                package.name, m))

    return result
