#!/usr/bin/env python2.6

"""Allows to integrate catalogs, e.g. unstable into testing.

The script generated shell commands that perform the catalog integration.  It
does not run them, because they need to be reviewed by a human before they can
be executed.

The script does not understand package versions.  It only displays commands
necessary to bring one catalog to the state of another catalog.
"""

from Cheetah import Template
import cjson
import gdbm
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
import re


CATALOG_MOD_TMPL = """#!/bin/bash
# Catalog modification (not integration yet): $catrel_from -> $catrel_to
# Generated by $prog


if ! grep buildfarm ~/.netrc
then
  touch ~/.netrc
  chmod 0600 ~/.netrc
  echo >> ~/.netrc \
    "machine buildfarm.opencsw.org login \${LOGNAME} password \$(cat /etc/opt/csw/releases/auth/\${LOGNAME})"
fi

set -x

readonly CURL="curl --netrc"
readonly REST_URL=http://buildfarm.opencsw.org/releases/

function _add_to_cat {
  \${CURL} -X PUT \${REST_URL}catalogs/$1/$2/$3/$4/ ; echo
}

function _del_from_cat {
  \${CURL} -X DELETE \${REST_URL}catalogs/$1/$2/$3/$4/ ; echo
}

#for catalogname in $sorted($diffs_by_catalogname):
#if "new_pkgs" in $diffs_by_catalogname[$catalogname]:
function new_pkg_$catalogname {
#for arch, osrel, new_pkg in $diffs_by_catalogname[$catalogname]["new_pkgs"]:
  # adding $new_pkg["basename"]
  _add_to_cat $catrel_to $arch $osrel $new_pkg["md5_sum"]
#end for
}
function undo_new_pkg_$catalogname {
#for arch, osrel, new_pkg in $diffs_by_catalogname[$catalogname]["new_pkgs"]:
  # UNDO adding $new_pkg["basename"]
  _del_from_cat $catrel_to $arch $osrel $new_pkg["md5_sum"]
#end for
}
#end if
#if "removed_pkgs" in $diffs_by_catalogname[$catalogname]:
function remove_pkg_$catalogname {
#for arch, osrel, rem_pkg in $diffs_by_catalogname[$catalogname]["removed_pkgs"]:
  # removing $rem_pkg["basename"]
  _del_from_cat $catrel_to $arch $osrel $rem_pkg["md5_sum"]
#end for
}
function undo_remove_pkg_$catalogname {
#for arch, osrel, rem_pkg in $diffs_by_catalogname[$catalogname]["removed_pkgs"]:
  # UNDO removing $rem_pkg["basename"]
  _add_to_cat $catrel_to $arch $osrel $rem_pkg["md5_sum"]
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
  _del_from_cat $catrel_to $arch $osrel $up_pkg_pair["from"]["md5_sum"]
  _add_to_cat $catrel_to $arch $osrel $up_pkg_pair["to"]["md5_sum"]
#end for
}
function undo_upgrade_$catalogname {
#for arch, osrel, up_pkg_pair in $diffs_by_catalogname[$catalogname]["updated_pkgs"]:
  # UNDO of $catalogname $up_pkg_pair["direction"] from $up_pkg_pair["from"]["version"] to $up_pkg_pair["to"]["version"]
  _del_from_cat $catrel_to $arch $osrel $up_pkg_pair["to"]["md5_sum"]
  _add_to_cat $catrel_to $arch $osrel $up_pkg_pair["from"]["md5_sum"]
#end for
}
#end if

#end for
#for catalogname in $sorted($diffs_by_catalogname):
#if "new_pkgs" in $diffs_by_catalogname[$catalogname]:
new_pkg_$catalogname#
#end if
#if "removed_pkgs" in $diffs_by_catalogname[$catalogname]:
remove_pkg_$catalogname#
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
$diffs_by_catalogname[$catalogname]["updated_pkgs"][0][2]["from"]["version"] to $diffs_by_catalogname[$catalogname]["updated_pkgs"][0][2]["to"]["version"]#
#end if
#end if
 # bundles:#
#for bundle in $bundles_by_catalogname[$catalogname]:
$bundle #
#end for

#end for
"""

class Error(Exception):
  """Generic error."""

class UsageError(Error):
  """Wrong usage."""


def IndexDictByField(d, field):
  return dict((x[field], x) for x in d)


def GetDiffsByCatalogname(catrel_from, catrel_to, include_downgrades,
                          include_version_changes):
  rest_client = rest.RestClient()
  def GetCatalog(rest_client, r_catrel, r_arch, r_osrel):
    key = r_catrel, r_arch, r_osrel
    catalog = rest_client.GetCatalog(*key)
    return (key, catalog)
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
  diffs_by_catalogname = ComposeDiffsByCatalogname(
      catalogs, catrel_from, catrel_to, include_version_changes,
      include_downgrades)
  return catalogs, diffs_by_catalogname

def ComposeDiffsByCatalogname(catalogs, catrel_from, catrel_to,
                              include_version_changes, include_downgrades):
  """Get a data structure indexed with catalognames.

  {
    catalogname: {
      "updated_pkgs": [
        [
          "sparc",
          "SunOS5.9",
          {
            "basename": ...,
            "catalogname": ...,
            "file_basename": ...,
            "md5_sum": ...,
            "mtime": ...,
            "rev": ...,
            "size": ...,
            "version": ...,
            "version_string": ...,
          }
        ],
      ],
      "new_pkgs": [
        ...
      ],
      "removed_pkgs": [
        ...
      ],
    },
  }
  """
  diffs_by_catalogname = {}
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
      cat_from_by_c = IndexDictByField(cat_from, "catalogname")
      cat_to_by_c = IndexDictByField(cat_to, "catalogname")
      comparator = catalog.CatalogComparator()
      new_pkgs, removed_pkgs, updated_pkgs = comparator.GetCatalogDiff(
          cat_to_by_c, cat_from_by_c)
      # By passing the catalogs (as arguments) in reverse order, we get
      # packages to be updated in new_pkgs, and so forth.
      for pkg in new_pkgs:
        catalogname_d = diffs_by_catalogname.setdefault(
            (pkg["catalogname"]), {})
        catalogname_d.setdefault("new_pkgs", []).append((arch, osrel, pkg))
      for pkg in removed_pkgs:
        catalogname_d = diffs_by_catalogname.setdefault(
            (pkg["catalogname"]), {})
        catalogname_d.setdefault("removed_pkgs", []).append((arch, osrel, pkg))
      for pkg_pair in updated_pkgs:
        update_decision_by_type = {
            "revision": True,
            "version": include_version_changes,
        }
        if (update_decision_by_type[pkg_pair["type"]]
            and (pkg_pair["direction"] == "upgrade" or include_downgrades)):
          pkg = pkg_pair["from"]
          catalogname_d = diffs_by_catalogname.setdefault(
              (pkg["catalogname"]), {})
          catalogname_d.setdefault("updated_pkgs", []).append((arch, osrel, pkg_pair))
  return diffs_by_catalogname


def main():
  parser = optparse.OptionParser()
  parser.add_option("--from-catalog",
      dest="catrel_from",
      default="unstable",
      help="Catalog release to integrate from, e.g. 'unstable'.")
  parser.add_option("--to-catalog",
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
  parser.add_option("--debug", dest="debug",
                    default=False, action="store_true")
  options, args = parser.parse_args()
  loglevel = logging.INFO
  if options.debug:
    loglevel = logging.DEBUG
  logging.basicConfig(level=loglevel)
  if not options.output_file:
    raise UsageError("Please specify the output file.  See --help.")
  catrel_from = options.catrel_from
  catrel_to = options.catrel_to
  if options.from_json:
    with open(options.from_json, "rb") as fd:
      logging.info("Loading %s", options.from_json)
      (bundles_by_md5,
          jsonable_catalogs,
          diffs_by_catalogname) = cjson.decode(fd.read())
      catalogs = dict(
        (tuple(cjson.decode(x)), jsonable_catalogs[x])
        for x in jsonable_catalogs)
  else:
    catalogs, diffs_by_catalogname = GetDiffsByCatalogname(
        catrel_from, catrel_to, options.include_downgrades,
        options.include_version_changes)
    bundles_by_md5 = {}
    bundles_missing = set()
    cp = rest.CachedPkgstats("pkgstats")
    for key in catalogs:
      if catalogs[key]: # could be None
        for pkg in catalogs[key]:
          # logging.debug("%r", pkg)
          md5 = pkg["md5_sum"]
          if md5 not in bundles_by_md5 and md5 not in bundles_missing:
            stats = cp.GetPkgstats(md5)
            bundle_key = "OPENCSW_BUNDLE"
            # pprint.pprint(stats)
            if stats:
              if bundle_key in stats["pkginfo"]:
                bundles_by_md5[md5] = stats["pkginfo"][bundle_key]
              else:
                logging.debug(
                    "%r (%r) does not have the bundle set",
                    stats["basic_stats"]["pkg_basename"], md5)
                bundles_missing.add(md5)
  # Here's a good place to calculate the mapping between catalognames and
  # bundle names.
  change_types = "new_pkgs", "removed_pkgs", "updated_pkgs"
  bundles_by_catalogname = {}
  for catalogname in diffs_by_catalogname:
    l = bundles_by_catalogname.setdefault(catalogname, set())
    for change_type in change_types:
      if change_type in diffs_by_catalogname[catalogname]:
        for change_info in diffs_by_catalogname[catalogname][change_type]:
          pkg = change_info[2]
          if "to" in pkg:
            md5s = [x["md5_sum"] for x in (pkg["from"], pkg["to"])]
          else:
            md5s = [pkg["md5_sum"]]
          for md5 in md5s:
            if md5 in bundles_by_md5:
              l.add(bundles_by_md5[md5])
  namespace = {
      "bundles_by_catalogname": bundles_by_catalogname,
      "bundles_by_md5": bundles_by_md5,
      "diffs_by_catalogname": diffs_by_catalogname,
      "catrel_to": catrel_to,
      "catrel_from": catrel_from,
      "prog": sys.argv[0],
  }
  if options.save_json:
    with open(options.save_json, "wb") as fd:
      jsonable_catalogs = dict((cjson.encode(x), catalogs[x]) for x in catalogs)
      fd.write(cjson.encode(
        (bundles_by_md5, jsonable_catalogs, diffs_by_catalogname)))
  t = Template.Template(CATALOG_MOD_TMPL, searchList=[namespace])
  if options.output_file:
    logging.info("Saving output to %s", options.output_file)
    with open(options.output_file, "wb") as fd:
      fd.write(unicode(t))
  else:
    sys.stdout.write(unicode(t))


if __name__ == '__main__':
  main()
