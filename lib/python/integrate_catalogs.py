#!/usr/bin/env python2.6

"""Allows to integrate catalogs, e.g. unstable into testing.

The script generated shell commands that perform the catalog integration.  It
does not run them, because they need to be reviewed by a human before they can
be executed.

The script does not understand package versions.  It only displays commands
necessary to bring one catalog to the state of another catalog.
"""

from Cheetah import Template
import json
import catalog
import common_constants
import logging
import opencsw
import optparse
import pprint
import rest
import sys
import urllib2


CATALOG_MOD_TMPL = """#!/bin/bash
# Catalog modification (not integration yet): $catrel_from -> $catrel_to
# Generated by $prog

set -x

PKGDB=bin/pkgdb

#for catalogname in $sorted($diffs_by_catalogname):
#if "new_pkgs" in $diffs_by_catalogname[$catalogname]:
function new_pkg_$catalogname {
#for arch, osrel, new_pkg in $diffs_by_catalogname[$catalogname]["new_pkgs"]:
  # adding $new_pkg["basename"]
  \${PKGDB} add-to-cat $osrel $arch $catrel_to $new_pkg["md5_sum"]
#end for
}
#end if
#if "removed_pkgs" in $diffs_by_catalogname[$catalogname]:
function remove_pkg_$catalogname {
#for arch, osrel, rem_pkg in $diffs_by_catalogname[$catalogname]["removed_pkgs"]:
  # removing $rem_pkg["basename"]
  \${PKGDB} del-from-cat $osrel $arch $catrel_to $rem_pkg["md5_sum"]
#end for
}
#end if
#if "updated_pkgs" in $diffs_by_catalogname[$catalogname]:
function #
#if $diffs_by_catalogname[$catalogname]["updated_pkgs"][0][2]["direction"] == "downgrade":
downgrade_#
#else
upgrade_#
#end if
$catalogname {
#for arch, osrel, up_pkg_pair in $diffs_by_catalogname[$catalogname]["updated_pkgs"]:
#if $up_pkg_pair["direction"] == "downgrade":
  # WARNING: DOWNGRADE
#end if
  # $catalogname $up_pkg_pair["direction"] from $up_pkg_pair["from"]["version"] to $up_pkg_pair["to"]["version"]
  \${PKGDB} del-from-cat $osrel $arch $catrel_to $up_pkg_pair["from"]["md5_sum"]
  \${PKGDB} add-to-cat $osrel $arch $catrel_to $up_pkg_pair["to"]["md5_sum"]
#end for
}
#end if

#end for
#for catalogname in $sorted($diffs_by_catalogname):
#if "new_pkgs" in $diffs_by_catalogname[$catalogname]:
new_pkg_$catalogname
#end if
#if "removed_pkgs" in $diffs_by_catalogname[$catalogname]:
remove_pkg_$catalogname
#end if
#if "updated_pkgs" in $diffs_by_catalogname[$catalogname]:
#if $diffs_by_catalogname[$catalogname]["updated_pkgs"][0][2]["direction"] == "downgrade":
downgrade_#
#else
upgrade_#
#end if
$catalogname#
 # $diffs_by_catalogname[$catalogname]["updated_pkgs"][0][2]["type"] #
#if $diffs_by_catalogname[$catalogname]["updated_pkgs"][0][2]["type"] == 'version'
$diffs_by_catalogname[$catalogname]["updated_pkgs"][0][2]["from"]["version"] to $diffs_by_catalogname[$catalogname]["updated_pkgs"][0][2]["to"]["version"]
#end if
#end if
#end for
"""


class Error(Exception):
  """Generic error."""

class UsageError(Error):
  """Wrong usage."""


def IndexByCatalogname(catalog):
  return dict((x["catalogname"], x) for x in catalog)


def GetDiffsByCatalogname(catrel_from, catrel_to, include_downgrades,
                          include_version_changes):
  rest_client = rest.RestClient()
  diffs_by_catalogname = {}
  def GetCatalog(rest_client, r_catrel, r_arch, r_osrel):
    catalog = rest_client.GetCatalog(r_catrel, r_arch, r_osrel)
    return ((r_catrel, r_arch, r_osrel), catalog)
  # TODO(maciej): Enable this once the multiprocessing module is fixed.
  # https://www.opencsw.org/mantis/view.php?id=4894
  # proc_pool = multiprocessing.Pool(20)
  catalogs_to_fetch_args = []
  for arch in common_constants.PHYSICAL_ARCHITECTURES:
    for osrel in common_constants.OS_RELS:
      for catrel in (catrel_from, catrel_to):
        catalogs_to_fetch_args.append((rest_client, catrel, arch, osrel))
  # Convert this to pool.map when multiprocessing if fixed.
  catalogs = dict(map(lambda x: GetCatalog(*x), catalogs_to_fetch_args))
  for arch in common_constants.PHYSICAL_ARCHITECTURES:
    logging.debug("Architecture: %s", arch)
    for osrel in common_constants.OS_RELS:
      logging.debug("OS release: %s", osrel)
      cat_from = catalogs[(catrel_from, arch, osrel)]
      cat_to = catalogs[(catrel_to, arch, osrel)]
      # Should use catalog comparator, but the data format is different
      if cat_from is None:
        cat_from = []
      if cat_to is None:
        cat_to = []
      cat_from_by_c = IndexByCatalogname(cat_from)
      cat_to_by_c = IndexByCatalogname(cat_to)
      comparator = catalog.CatalogComparator()
      new_pkgs, removed_pkgs, updated_pkgs = comparator.GetCatalogDiff(
          cat_to_by_c, cat_from_by_c)
      # By passing the catalogs (as arguments) in reverse order, we get
      # packages to be updated in new_pkgs, and so forth.
      for pkg in new_pkgs:
        catalogname_d = diffs_by_catalogname.setdefault(pkg["catalogname"], {})
        catalogname_d.setdefault("new_pkgs", []).append((arch, osrel, pkg))
      for pkg in removed_pkgs:
        catalogname_d = diffs_by_catalogname.setdefault(pkg["catalogname"], {})
        catalogname_d.setdefault("removed_pkgs", []).append((arch, osrel, pkg))
      for pkg_pair in updated_pkgs:
        update_decision_by_type = {
            "revision": True,
            "version": include_version_changes
        }
        if (update_decision_by_type[pkg_pair["type"]]
            and (pkg_pair["direction"] == "upgrade" or include_downgrades)):
          pkg = pkg_pair["from"]
          catalogname_d = diffs_by_catalogname.setdefault(pkg["catalogname"], {})
          catalogname_d.setdefault("updated_pkgs", []).append((arch, osrel, pkg_pair))
  return diffs_by_catalogname


def main():
  parser = optparse.OptionParser()
  parser.add_option("--catrel-from",
      dest="catrel_from",
      default="unstable",
      help="Catalog release to integrate from, e.g. 'unstable'.")
  parser.add_option("--catrel-to",
      dest="catrel_to",
      default="testing",
      help="Catalog release to integrate to, e.g. 'testing'.")
  parser.add_option("--from-json", dest="from_json",
      help=("If specified, loads data from a JSON file instead of polling "
            "the database."))
  parser.add_option("--save-json", dest="save_json",
      help="If specified, saves JSON data to a file.")
  parser.add_option("-o", "--output-file", dest="output_file",
      help="Filename to save output to.")
  parser.add_option("--no-include-downgrades", dest="include_downgrades",
      default=True, action="store_false",
      help="Skip package downgrades.")
  parser.add_option("--no-include-version-changes",
      dest="include_version_changes",
      default=True, action="store_false",
      help="Skip version upgrades (only accept revision upgrades).")
  options, args = parser.parse_args()
  logging.basicConfig(level=logging.DEBUG)
  if not options.output_file:
    raise UsageError("Please specify the output file.  See --help.")
  catrel_from = options.catrel_from
  catrel_to = options.catrel_to
  if options.from_json:
    with open(options.from_json, "rb") as fd:
      diffs_by_catalogname = json.load(fd)
  else:
    diffs_by_catalogname = GetDiffsByCatalogname(
        catrel_from, catrel_to, options.include_downgrades,
        options.include_version_changes)
  namespace = {
      "diffs_by_catalogname": diffs_by_catalogname,
      "catrel_to": catrel_to,
      "catrel_from": catrel_from,
      "prog": sys.argv[0],
  }
  if options.save_json:
    with open(options.save_json, "wb") as fd:
      json.dump(diffs_by_catalogname, fd)
  t = Template.Template(CATALOG_MOD_TMPL, searchList=[namespace])
  if options.output_file:
    logging.info("Saving output to %s", options.output_file)
    with open(options.output_file, "wb") as fd:
      fd.write(unicode(t))
  else:
    sys.stdout.write(unicode(t))


if __name__ == '__main__':
  main()
