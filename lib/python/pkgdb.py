#!/opt/csw/bin/python2.6
# coding=utf-8
#
# $Id$

import optparse
import models as m
import sqlobject
import cPickle
import logging
import code
import os
import os.path
import re
import socket
import sys
import package_checks
from Cheetah.Template import Template

USAGE = """usage: %prog show errors <md5sum> [ ... ]
       %prog show pkg <pkgname> [ ... ]
       %prog gen-html <md5sum> [ ... ]
       """
SHOW_PKG_TMPL = """catalogname:    $catalogname
pkgname:        $pkginst.pkgname
basename:       $basename
mtime:          $mtime
md5_sum:        $md5_sum
arch:           $arch.name
os_rel:         $os_rel.short_name
maintainer:     $maintainer.email
latest:         $latest
version_string: $version_string
rev:            $rev
stats_version:  $stats_version
"""


def GetPkg(some_id):
  logging.debug("Selecting from db: %s", repr(some_id))
  res = m.Srv4FileStats.select(
      sqlobject.OR(
        m.Srv4FileStats.q.md5_sum==some_id,
        m.Srv4FileStats.q.catalogname==some_id))
  try:
    srv4 = res.getOne()
  except sqlobject.main.SQLObjectIntegrityError, e:
    logging.warning(e)
    for row in res:
      print "- %s %s %s" % (row.md5_sum, row.version_string, row.mtime)
    raise
  logging.debug("Got: %s", srv4)
  return srv4

def main():
  parser = optparse.OptionParser(USAGE)
  parser.add_option("-d", "--debug", dest="debug",
                    default=False, action="store_true",
                    help="Turn on debugging messages")
  options, args = parser.parse_args()
  if options.debug:
    logging.basicConfig(level=logging.DEBUG)
  else:
    logging.basicConfig(level=logging.INFO)
  command = args[0]
  args = args[1:]
  if command == 'show':
    subcommand = args[0]
    args = args[1:]
  else:
    subcommand = None

  db_path = os.path.join(
      os.environ["HOME"],
      ".checkpkg",
      "checkpkg-db-%s" % socket.getfqdn())
  sqo_conn = sqlobject.connectionForURI('sqlite:%s' % db_path)
  sqlobject.sqlhub.processConnection = sqo_conn

  md5_sums = args

  if (command, subcommand) == ('show', 'errors'):
    for md5_sum in md5_sums:
      srv4 = GetPkg(md5_sum)
      res = m.CheckpkgErrorTag.select(m.CheckpkgErrorTag.q.srv4_file==srv4)
      for row in res:
        print row.pkgname, row.tag_name, row.tag_info
  if (command, subcommand) == ('show', 'overrides'):
    for md5_sum in md5_sums:
      srv4 = GetPkg(md5_sum)
      res = m.CheckpkgOverride.select(m.CheckpkgOverride.q.srv4_file==srv4)
      for row in res:
        print row.pkgname, row.tag_name, row.tag_info
  if (command, subcommand) == ('show', 'pkg'):
    for md5_sum in md5_sums:
      srv4 = GetPkg(md5_sum)
      t = Template(SHOW_PKG_TMPL, searchList=[srv4])
      sys.stdout.write(unicode(t))
  if command == 'gen-html':
    pkgstats = []
    # Add error tags
    for md5_sum in md5_sums:
      srv4 = GetPkg(md5_sum)
      data = cPickle.loads(str(srv4.data))
      if "OPENCSW_REPOSITORY" in data["pkginfo"]:
        build_src = data["pkginfo"]["OPENCSW_REPOSITORY"]
        build_src = re.sub(r"@(\d+)$", r"?rev=\1", build_src)
      else:
        build_src = None
      data["build_src"] = build_src
      pkgstats.append(data)
    # This assumes the program is run as "bin/pkgdb", and not "lib/python/pkgdb.py".
    tmpl_filename = os.path.join(os.path.split(__file__)[0],
                                 "..",
                                 "lib",
                                 "python",
                                 "pkg-review-template.html")
    tmpl_str = open(tmpl_filename, "r").read()
    t = Template(tmpl_str, searchList=[{
      "pkgstats": pkgstats,
      "hachoir_machines": package_checks.HACHOIR_MACHINES,
      }])
    sys.stdout.write(unicode(t))


if __name__ == '__main__':
  main()
