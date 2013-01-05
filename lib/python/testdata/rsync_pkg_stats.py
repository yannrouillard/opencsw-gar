pkgstats = [{'bad_paths': {},
  'basic_stats': {'catalogname': 'rsync',
                  'parsed_basename': {'arch': 'sparc',
                                      'catalogname': 'rsync',
                                      'full_version_string': '3.0.7,REV=2010.02.17',
                                      'osrel': 'SunOS5.8',
                                      'revision_info': {'REV': '2010.02.17'},
                                      'vendortag': 'CSW',
                                      'version': '3.0.7',
                                      'version_info': {'major version': '3',
                                                       'minor version': '0',
                                                       'patchlevel': '7'}},
                  'pkg_basename': 'rsync-3.0.7,REV=2010.02.17-SunOS5.8-sparc-CSW.pkg.gz',
                  'pkg_path': '/tmp/pkg_wq7Wyx/rsync-3.0.7,REV=2010.02.17-SunOS5.8-sparc-CSW.pkg.gz',
                  'pkgname': 'CSWrsync',
                  'stats_version': 7L},
  'binaries': ['opt/csw/bin/sparcv8/rsync', 'opt/csw/bin/sparcv9/rsync'],
  'binaries_dump_info': [{'RPATH set': True,
                          'RUNPATH RPATH the same': True,
                          'RUNPATH set': True,
                          'base_name': 'rsync',
                          'needed sonames': ['libpopt.so.0',
                                             'libsec.so.1',
                                             'libiconv.so.2',
                                             'libsocket.so.1',
                                             'libnsl.so.1',
                                             'libc.so.1'],
                          'path': 'opt/csw/bin/sparcv8/rsync',
                          'runpath': ('/opt/csw/lib/$ISALIST',
                                      '/opt/csw/lib')},
                         {'RPATH set': True,
                          'RUNPATH RPATH the same': True,
                          'RUNPATH set': True,
                          'base_name': 'rsync',
                          'needed sonames': ['libpopt.so.0',
                                             'libsec.so.1',
                                             'libiconv.so.2',
                                             'libsocket.so.1',
                                             'libnsl.so.1',
                                             'libc.so.1'],
                          'path': 'opt/csw/bin/sparcv9/rsync',
                          'runpath': ('/opt/csw/lib/$ISALIST',
                                      '/opt/csw/lib/64')}],
  'depends': [('CSWcommon',
               'CSWcommon common - common files and dirs for CSW packages '),
              ('CSWisaexec',
               'CSWisaexec isaexec - sneaky wrapper around Sun isaexec '),
              ('CSWiconv', 'CSWiconv libiconv - GNU iconv library '),
              ('CSWlibpopt',
               'CSWlibpopt libpopt - Popt is a C library for parsing command line parameters ')],
  'files_metadata': [{'mime_type': 'text/troff; charset=us-ascii',
                      'path': 'opt/csw/share/man/man5/rsyncd.conf.5'},
                     {'mime_type': 'text/troff; charset=us-ascii',
                      'path': 'opt/csw/share/man/man1/rsync.1'},
                     {'mime_type': 'text/plain; charset=us-ascii',
                      'path': 'opt/csw/share/doc/rsync/license'},
                     {'endian': 'Big endian',
                      'machine_id': 43,
                      'mime_type': 'application/x-executable; charset=binary',
                      'mime_type_by_hachoir': u'application/x-executable',
                      'path': 'opt/csw/bin/sparcv9/rsync'},
                     {'endian': 'Big endian',
                      'machine_id': 2,
                      'mime_type': 'application/x-executable; charset=binary',
                      'mime_type_by_hachoir': u'application/x-executable',
                      'path': 'opt/csw/bin/sparcv8/rsync'}],
  'isalist': ('sparcv9+vis2',
              'sparcv9+vis',
              'sparcv9',
              'sparcv8plus+vis2',
              'sparcv8plus+vis',
              'sparcv8plus',
              'sparcv8',
              'sparcv8-fsmuld',
              'sparcv7',
              'sparc'),
  'ldd_info': {
      'opt/csw/bin/sparcv8/rsync': [],
      'opt/csw/bin/sparcv9/rsync': [],
    },
  'binaries_elf_info': {
      'opt/csw/bin/sparcv8/rsync': {
        'version definition': [],
        'version needed': [],
        'symbol table': [
          { 'soname': 'libpopt.so.0', 'symbol': 'foo', 'flags': 'DBL', 'shndx': 'UNDEF', 'bind': 'GLOB' },
          { 'soname': 'libsec.so.1', 'symbol': 'foo', 'flags': 'DBL', 'shndx': 'UNDEF', 'bind': 'GLOB' },
          { 'soname': 'libiconv.so.2', 'symbol': 'foo', 'flags': 'DBL', 'shndx': 'UNDEF', 'bind': 'GLOB' },
          { 'soname': 'libsocket.so.1', 'symbol': 'foo', 'flags': 'DBL', 'shndx': 'UNDEF', 'bind': 'GLOB' },
          { 'soname': 'libnsl.so.1', 'symbol': 'foo', 'flags': 'DBL', 'shndx': 'UNDEF', 'bind': 'GLOB' },
          { 'soname': 'libc.so.1', 'symbol': 'foo', 'flags': 'DBL', 'shndx': 'UNDEF', 'bind': 'GLOB' },
        ]
      },
      'opt/csw/bin/sparcv9/rsync': {
        'version definition': [],
        'version needed': [],
        'symbol table': [
          { 'soname': 'libpopt.so.0', 'symbol': 'foo', 'flags': 'DBL', 'shndx': 'UNDEF', 'bind': 'GLOB' },
          { 'soname': 'libsec.so.1', 'symbol': 'foo', 'flags': 'DBL', 'shndx': 'UNDEF', 'bind': 'GLOB' },
          { 'soname': 'libiconv.so.2', 'symbol': 'foo', 'flags': 'DBL', 'shndx': 'UNDEF', 'bind': 'GLOB' },
          { 'soname': 'libsocket.so.1', 'symbol': 'foo', 'flags': 'DBL', 'shndx': 'UNDEF', 'bind': 'GLOB' },
          { 'soname': 'libnsl.so.1', 'symbol': 'foo', 'flags': 'DBL', 'shndx': 'UNDEF', 'bind': 'GLOB' },
          { 'soname': 'libc.so.1', 'symbol': 'foo', 'flags': 'DBL', 'shndx': 'UNDEF', 'bind': 'GLOB' },
        ]
      }
  },
  'overrides': [],
  'pkgchk': {'return_code': 0,
             'stderr_lines': ['rm: Cannot remove any directory in the path of the current working directory',
                              '/var/tmp/aaacuaqYV/CSWrsync'],
             'stdout_lines': ['Checking uninstalled stream format package <CSWrsync> from </tmp/pkg_wq7Wyx/rsync-3.0.7,REV=2010.02.17-SunOS5.8-sparc-CSW.pkg>',
                              '## Checking control scripts.',
                              '## Checking package objects.',
                              '## Checking is complete.']},
  'pkginfo': {'ARCH': 'sparc',
              'CATEGORY': 'application',
              'CLASSES': 'none',
              'EMAIL': 'maciej@opencsw.org',
              'HOTLINE': 'http://www.opencsw.org/bugtrack/',
              'NAME': 'rsync - utility which provides fast incremental file transfer',
              'OPENCSW_CATALOGNAME': 'rsync',
              'OPENCSW_MODE64': '32/64/isaexec',
              'OPENCSW_REPOSITORY': 'https://gar.svn.sourceforge.net/svnroot/gar/csw/mgar/pkg/rsync/trunk@8611',
              'PKG': 'CSWrsync',
              'PSTAMP': 'maciej@build8s-20100217094608',
              'VENDOR': 'http://rsync.samba.org/ packaged for CSW by Maciej Blizinski',
              'VERSION': '3.0.7,REV=2010.02.17',
              'WORKDIR_FIRSTMOD': '../build-isa-sparcv8'},
  'pkgmap': [{'class': None,
              'group': None,
              'line': ': 1 2912',
              'mode': None,
              'path': None,
              'type': '1',
              'user': None},
             {'class': 'none',
              'group': None,
              'line': '1 l none /opt/csw/bin/rsync=/opt/csw/bin/isaexec',
              'mode': None,
              'path': '/opt/csw/bin/rsync',
              'type': 'l',
              'user': None},
             {'class': 'none',
              'group': 'bin',
              'line': '1 f none /opt/csw/bin/sparcv8/rsync 0755 root bin 585864 12576 1266395028',
              'mode': '0755',
              'path': '/opt/csw/bin/sparcv8/rsync',
              'type': 'f',
              'user': 'root'},
             {'class': 'none',
              'group': 'bin',
              'line': '1 f none /opt/csw/bin/sparcv9/rsync 0755 root bin 665520 60792 1266395239',
              'mode': '0755',
              'path': '/opt/csw/bin/sparcv9/rsync',
              'type': 'f',
              'user': 'root'},
             {'class': 'none',
              'group': 'bin',
              'line': '1 d none /opt/csw/share/doc/rsync 0755 root bin',
              'mode': '0755',
              'path': '/opt/csw/share/doc/rsync',
              'type': 'd',
              'user': 'root'},
             {'class': 'none',
              'group': 'bin',
              'line': '1 f none /opt/csw/share/doc/rsync/license 0644 root bin 35147 30328 1266396366',
              'mode': '0644',
              'path': '/opt/csw/share/doc/rsync/license',
              'type': 'f',
              'user': 'root'},
             {'class': 'none',
              'group': 'bin',
              'line': '1 d none /opt/csw/share/man/man1 0755 root bin',
              'mode': '0755',
              'path': '/opt/csw/share/man/man1',
              'type': 'd',
              'user': 'root'},
             {'class': 'none',
              'group': 'bin',
              'line': '1 f none /opt/csw/share/man/man1/rsync.1 0644 root bin 159739 65016 1266395027',
              'mode': '0644',
              'path': '/opt/csw/share/man/man1/rsync.1',
              'type': 'f',
              'user': 'root'},
             {'class': 'none',
              'group': 'bin',
              'line': '1 d none /opt/csw/share/man/man5 0755 root bin',
              'mode': '0755',
              'path': '/opt/csw/share/man/man5',
              'type': 'd',
              'user': 'root'},
             {'class': 'none',
              'group': 'bin',
              'line': '1 f none /opt/csw/share/man/man5/rsyncd.conf.5 0644 root bin 36372 24688 1266395027',
              'mode': '0644',
              'path': '/opt/csw/share/man/man5/rsyncd.conf.5',
              'type': 'f',
              'user': 'root'},
             {'class': None,
              'group': None,
              'line': '1 i copyright 69 6484 1266396366',
              'mode': None,
              'path': None,
              'type': 'i',
              'user': None},
             {'class': None,
              'group': None,
              'line': '1 i depend 236 21212 1266396368',
              'mode': None,
              'path': None,
              'type': 'i',
              'user': None},
             {'class': None,
              'group': None,
              'line': '1 i pkginfo 511 43247 1266396371',
              'mode': None,
              'path': None,
              'type': 'i',
              'user': None}]}]
