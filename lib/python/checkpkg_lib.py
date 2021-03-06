# A collection of checkpkg-specific classes.
#
# This file is supposed to drain the checkpkg.py file until is becomes
# empty and goes away.

import collections
import copy
import getpass
import itertools
import logging
import operator
import os.path
import pprint
import progressbar
import re
import sqlobject
import textwrap

from Cheetah import Template
from sqlobject import sqlbuilder

from lib.python import common_constants
from lib.python import configuration
from lib.python import database
from lib.python import errors
from lib.python import models as m
from lib.python import mute_progressbar
from lib.python import representations
from lib.python import rest
from lib.python import sharedlib_utils
from lib.python import tag

DESCRIPTION_RE = r"^([\S]+) - (.*)$"

SYS_DEFAULT_RUNPATH = [
    "/usr/lib/$ISALIST",
    "/usr/lib",
    "/lib/$ISALIST",
    "/lib",
]


class CatalogDatabaseError(errors.Error):
  """Problem with the catalog database."""


class DataError(errors.Error):
  """A problem with reading required data."""


class ConfigurationError(errors.Error):
  """A problem with checkpkg configuration."""


class InternalDataError(errors.Error):
  """Problem with internal checkpkg data structures."""


REPORT_TMPL = u"""#if $missing_deps or $surplus_deps or $orphan_sonames
Dependency issues of $pkgname:
#end if
#if $missing_deps
#for $pkg, $reasons in $sorted($missing_deps)
$pkg is needed by $pkgname, because:
#for $reason in $reasons
 - $reason
#end for
RUNTIME_DEP_PKGS_$pkgname += $pkg
#end for
#end if
#if $surplus_deps
If you don't know of any reasons to include these dependencies, you might remove them:
#for $pkg in $sorted($surplus_deps)
? $pkg
#end for
#end if
"""

SCREEN_ERROR_REPORT_TMPL = u"""#if $errors
#if $debug
ERROR: One or more errors have been found by $name.
#end if
#for $pkgname in $errors
$pkgname:
#for $error in $errors[$pkgname]
#if $debug
  $repr($error)
#elif $error.msg
$textwrap.fill($error.msg, 78, initial_indent="# ", subsequent_indent="# ")
# -> $repr($error)

#end if
#end for
#end for
#else
#if $debug
OK: $repr($name) module found no problems.
#end if
#end if
#if $messages
#for $msg in $messages
$textwrap.fill($msg, 78, initial_indent=" * ", subsequent_indent="   ")
#end for
#end if
#if $gar_lines

# Checkpkg suggests adding the following lines to the GAR recipe:
# This is a summary; see above for details.
#for $line in $gar_lines
$line
#end for
#end if
"""

# http://www.cheetahtemplate.org/docs/users_guide_html_multipage/language.directives.closures.html
TAG_REPORT_TMPL = u"""#if $errors
# Tags reported by $name module
#for $pkgname in $errors
#for $tag in $errors[$pkgname]
#if $tag.msg
$textwrap.fill($tag.msg, 70, initial_indent="# ", subsequent_indent="# ")
#end if
$pkgname: ${tag.tag_name}#if $tag.tag_info# $tag.tag_info#end if#
#end for
#end for
#end if
"""


def ExtractDescription(pkginfo):
  desc_re = re.compile(DESCRIPTION_RE)
  m = re.match(desc_re, pkginfo["NAME"])
  return m.group(2) if m else None


def ExtractMaintainerName(pkginfo):
  maint_re = re.compile("^.*for CSW by (.*)$")
  m = re.match(maint_re, pkginfo["VENDOR"])
  return m.group(1) if m else None


def ExtractBuildUsername(pkginfo):
  m = re.match(common_constants.PSTAMP_RE, pkginfo["PSTAMP"])
  return m.group("username") if m else None


class SqlobjectHelperMixin(object):

  def __init__(self):
    super(SqlobjectHelperMixin, self).__init__()
    self.triad_cache = {}

  def GetSqlobjectTriad(self, osrel, arch, catrel):
    key = (osrel, arch, catrel)
    if key not in self.triad_cache:
      logging.debug("GetSqlobjectTriad(%s,  %s,  %s)", osrel, arch, catrel)
      sqo_arch = m.Architecture.select(
          m.Architecture.q.name==arch).getOne()
      sqo_osrel = m.OsRelease.select(
          m.OsRelease.q.short_name==osrel).getOne()
      sqo_catrel = m.CatalogRelease.select(
          m.CatalogRelease.q.name==catrel).getOne()
      self.triad_cache[key] = sqo_osrel, sqo_arch, sqo_catrel
    return self.triad_cache[key]


def ElfinfoBlobToStruct(elfdump_data):
  # json doesn't preserve namedtuple so we do some post-processing
  # to transform symbol info from List to NamedTuple
  symbols = elfdump_data['symbol table']
  for idx, symbol_as_list in enumerate(symbols):
    symbols[idx] = representations.ElfSymInfo(*symbol_as_list)

  return elfdump_data


class LazyElfinfo(object):
  """Used at runtime for lazy fetches of elfdump info data."""

  def __init__(self, rest_client):
    self.rest_client = rest_client

  def __getitem__(self, md5_sum):
    elfdump_data = self.rest_client.GetBlob('elfdump', md5_sum)
    return ElfinfoBlobToStruct(elfdump_data)


class CheckpkgManagerBase(SqlobjectHelperMixin):
  """Common functions between the older and newer calling functions."""

  def __init__(self, name, sqo_pkgs_list, osrel, arch, catrel, debug=False,
      show_progress=False):
    super(CheckpkgManagerBase, self).__init__()
    self.debug = debug
    self.name = name
    self.sqo_pkgs_list = sqo_pkgs_list
    self.osrel = osrel
    self.arch = arch
    self.catrel = catrel
    self.show_progress = show_progress
    self._ResetState()
    self.individual_checks = []
    self.set_checks = []
    config = configuration.GetConfig()
    username, password = rest.GetUsernameAndPassword()
    self.rest_client = rest.RestClient(
        pkgdb_url=config.get('rest', 'pkgdb'),
        releases_url=config.get('rest', 'releases'),
        username=username,
        password=password)

  def _ResetState(self):
    self.errors = []
    self.packages = []

  def GetProgressBar(self):
    if self.show_progress and not self.debug:
      return progressbar.ProgressBar()
    else:
      return mute_progressbar.MuteProgressBar()

  def GetSqlobjectTriad(self):
     return super(CheckpkgManagerBase, self).GetSqlobjectTriad(
         self.osrel, self.arch, self.catrel)

  def FormatReports(self, errors, messages, gar_lines):
    namespace = {
        "name": self.name,
        "errors": errors,
        "debug": self.debug,
        "textwrap": textwrap,
        "messages": messages,
        "gar_lines": gar_lines,
    }
    screen_t = Template.Template(SCREEN_ERROR_REPORT_TMPL, searchList=[namespace])
    tags_report_t = Template.Template(TAG_REPORT_TMPL, searchList=[namespace])
    return screen_t, tags_report_t

  def SetErrorsToDict(self, set_errors, a_dict):
    # These were generated by a set, but are likely to be bound to specific
    # packages. We'll try to preserve the package assignments.
    errors = copy.copy(a_dict)
    for tag in set_errors:
      if tag.pkgname:
        if not tag.pkgname in errors:
          errors[tag.pkgname] = []
        errors[tag.pkgname].append(tag)
      else:
        if "package-set" not in errors:
          errors["package-set"] = []
        errors["package-set"].append(tag)
    return errors

  def GetOptimizedAllStats(self, stats_obj_list):
    logging.info("Unwrapping candies...")
    pkgs_data = []
    counter = itertools.count()
    length = len(stats_obj_list)
    pbar = self.GetProgressBar()
    pbar.maxval = length
    pbar.start()
    for stats_obj in stats_obj_list:
      # This bit is tightly tied to the data structures returned by
      # PackageStats.
      #
      # Python strings are already implementing the flyweight pattern. What's
      # left is lists and dictionaries.
      raw_pkg_data = self.rest_client.GetBlob('pkgstats', stats_obj.md5_sum)
      # Registering a callback allowing the receiver to retrieve the elfdump
      # information when necessary.
      raw_pkg_data['elfdump_info'] = LazyElfinfo(self.rest_client)
      pkgs_data.append(raw_pkg_data)
      pbar.update(counter.next())
    pbar.finish()
    return pkgs_data

  def Run(self):
    """Runs all the checks

    Returns a tuple of (exit code, report).
    """
    self._ResetState()
    assert self.sqo_pkgs_list, "The list of packages must not be empty."
    db_stat_objs_by_pkgname = {}
    for pkg in self.sqo_pkgs_list:
      db_stat_objs_by_pkgname[pkg.pkginst.pkgname] = pkg
    logging.debug("Deleting old errors from the database.")
    sqo_os_rel, sqo_arch, sqo_catrel = self.GetSqlobjectTriad()
    overrides_by_pkgname = {}
    for pkgname, db_obj in db_stat_objs_by_pkgname.iteritems():
      db_obj.RemoveCheckpkgResults(sqo_os_rel, sqo_arch, sqo_catrel)
      overrides_by_pkgname[pkgname] = list(db_obj.GetOverridesResult())
    errors, messages, gar_lines = self.GetAllTags(self.sqo_pkgs_list)
    pbar = self.GetProgressBar()
    pbar.maxval = len(errors) + 1
    count = itertools.count(1)
    logging.info("Stuffing the candies under the pillow...")
    pbar.start()
    for pkgname, es in errors.iteritems():
      logging.debug("Saving errors of %s to the database.", pkgname)
      for e in es:
        if e.pkgname not in db_stat_objs_by_pkgname:
          logging.warning("Not saving an error for %s.", e.pkgname)
          continue
        tag_info=e.tag_info
        if tag_info is not None:
          if not isinstance(tag_info, unicode):
            tag_info=unicode(tag_info, "utf-8")
        error_tag_in_db = m.CheckpkgErrorTag(
            srv4_file=db_stat_objs_by_pkgname[e.pkgname],
            pkgname=e.pkgname,
            tag_name=e.tag_name,
            tag_info=tag_info,
            msg=e.msg,
            os_rel=sqo_os_rel,
            catrel=sqo_catrel,
            arch=sqo_arch)
        # Check whether any of the overrides apply to this tag, and
        # store the result.
        overridden = False
        for override in overrides_by_pkgname[pkgname]:
          if override.DoesApply(error_tag_in_db):
            logging.debug("%s overrides %s", override, error_tag_in_db)
            overridden = True
            break
        error_tag_in_db.overridden = overridden
      pbar.update(count.next())
    pbar.finish()
    flat_error_list = reduce(operator.add, errors.values(), [])
    screen_report, tags_report = self.FormatReports(errors, messages, gar_lines)
    exit_code = 0
    return (exit_code, screen_report, tags_report)


NeededFile = collections.namedtuple('NeededFile',
                                    'pkgname full_path reason')
NeededPackage = collections.namedtuple('NeededPackage',
                                       'pkgname needed_pkg reason')


class CheckInterfaceBase(object):
  """Provides an interface for checking functions.

  It wraps access to the catalog database.
  """

  def __init__(self, osrel, arch, catrel, catalog, pkg_set_files, lines_dict=None,
               rest_client=None):
    """
    Args:
      osrel: OS release
      arch: Architecture
      catrel: Catalog release
      catalog: ?
      pkgs_set_files: A dictionary of collections of pairs path / basename
      lines_dict: ?
      rest_client: the rest interface client

    An example:
    {
      "CSWfoo": frozenset([
        ("/opt/csw/bin", "foo"),
        ...
      ]),
      "CSWbar": ...,
      ...
    }
    """
    self.osrel = osrel
    self.arch = arch
    self.catrel = catrel
    self.catalog = catalog
    self.common_paths = {}
    self.pkgs_by_path_cache = {}
    if lines_dict:
      self.lines_dict = lines_dict
    else:
      self.lines_dict = {}
    # Lists:
    # [('/opt/csw/lib/libfoo.so.1', '/opt/csw/bin/foo needs libfoo.so.1'), ... ]
    self.needed_files = []
    # [('CSWfoo', 'Provides an interpreter of foo'), ... ]
    self.needed_pkgs = []
    self.__errors = []
    # Making an index of files that is easy to look up
    self.pkg_set_files = pkg_set_files
    self.pkgs_by_file = {}
    self.pkgs_by_basename = {}
    for pkgname in self.pkg_set_files:
      for base_path, base_name in self.pkg_set_files[pkgname]:
        full_path = os.path.join(base_path, base_name)
        self.pkgs_by_file.setdefault(full_path, set())
        self.pkgs_by_file[full_path].add(pkgname)
        self.pkgs_by_basename.setdefault(base_name, {})
        self.pkgs_by_basename[base_name].setdefault(base_path, set())
        self.pkgs_by_basename[base_name][base_path].add(pkgname)
    self.rest_client = rest_client

  def GetErrors(self):
    return self.__errors

  errors = property(GetErrors)

  def AddError(self, error):
    self.__errors.append(error)

  def GetPathsAndPkgnamesByBasename(self, basename):
    """Proxies calls to class member."""
    paths_and_pkgs = self.rest_client.GetPathsAndPkgnamesByBasename(
      self.catrel, self.arch, self.osrel, basename)
    # Removing references to packages under test
    for catalog_path in paths_and_pkgs:
      for pkgname in self.pkg_set_files:
        if pkgname in paths_and_pkgs[catalog_path]:
          paths_and_pkgs[catalog_path].remove(pkgname)
    # Adding files from packages under test
    if basename in self.pkgs_by_basename:
      for path in self.pkgs_by_basename[basename]:
        for pkg in self.pkgs_by_basename[basename][path]:
          paths = paths_and_pkgs.setdefault(path, [])
          paths.append(pkg)
    return paths_and_pkgs

  def GetPkgByPath(self, file_path):
    """Proxies calls to self.system_pkgmap."""
    key = (file_path, self.osrel, self.arch, self.catrel)
    if not key in self.pkgs_by_path_cache:
      pkgs_in_catalog = self.catalog.GetPkgByPath(
          file_path, self.osrel, self.arch, self.catrel)
      # This response comes from catalog; we need to simulate the state the
      # catalog would have if the set under test in the catalog.  First, we
      # remove old versions of packages under test.
      pkgs = set(pkgs_in_catalog.difference(set(self.pkg_set_files)))
      if file_path in self.pkgs_by_file:
        for pkg in self.pkgs_by_file[file_path]:
          pkgs.add(pkg)
      self.pkgs_by_path_cache[key] = pkgs
    return self.pkgs_by_path_cache[key]

  def GetInstalledPackages(self):
    return self.catalog.GetInstalledPackages(
        self.osrel, self.arch, self.catrel)

  def _GetPathsForArch(self, arch):
    if not arch in self.lines_dict:
      base_name = "commondirs-%s" % arch
      paths = [
        os.path.join(os.path.dirname(__file__), "..", "..", "etc", base_name),
        os.path.join(common_constants.OPENCSW_SHARE, "gar", base_name)
      ]
      path_found = False
      for file_name in paths:
        if not os.path.exists(file_name):
          continue
        # There is a race condition here, but we don't worry about it.
        path_found = True
        logging.debug("opening %s", file_name)
        with open(file_name, "r") as f:
          self.lines_dict[arch] = f.read().splitlines()
        break
      if not path_found:
        raise DataError("Could not find the %s file." % base_name)
    return self.lines_dict[arch]

  def GetCommonPaths(self, arch):
    """Returns a list of paths for architecture, from gar/etc/commondirs*."""
    # TODO: If this was cached, it could save a significant amount of time.
    if arch not in ('i386', 'sparc', 'all'):
      logging.warn("Wrong arch: %s", repr(arch))
      return []
    if arch == 'all':
      archs = ('i386', 'sparc')
    else:
      archs = [arch]
    lines = []
    for arch in archs:
      lines.extend(self._GetPathsForArch(arch))
    return lines

  def _NeedFile(self, pkgname, full_path, reason):
    """Declares that a package requires one of the files for a reason.

    Special attention needs to be paid to reasons.  If multiple files
    are needed for the same reason, it's understood that any of them
    satisfies the dependency.  Reasons passed to this function have to
    be specific, e.g. "provides libfoo.so.1".  A good example of a bad
    reason would be "a shared library" - it doesn't provide any
    specifics.
    """
    self.needed_files.append(NeededFile(pkgname, full_path, reason))

  def _NeedPackage(self, pkgname, needed_pkg, reason):
    self.needed_pkgs.append(NeededPackage(pkgname, needed_pkg, reason))

  def ReportErrorForPkgname(self, pkgname, tag_name, tag_info=None, msg=None):
    # TODO: Make this bit use the CheckpkgErrorTag class from models.py
    checkpkg_tag = tag.CheckpkgTag(pkgname, tag_name, tag_info, msg=msg)
    self.AddError(checkpkg_tag)

  def GetElfdumpInfo(self, md5_sum):
    elfdump_data = self.rest_client.GetBlob('elfdump', md5_sum)
    return ElfinfoBlobToStruct(elfdump_data)


class IndividualCheckInterface(CheckInterfaceBase):
  """To be passed to the checking functions.

  Wraps the creation of tag.CheckpkgTag objects.
  """

  def __init__(self, pkgname, osrel, arch, catrel, catalog, pkg_set_files, rest_client):
    super(IndividualCheckInterface, self).__init__(
        osrel, arch, catrel, catalog, pkg_set_files, rest_client=rest_client)
    self.pkgname = pkgname

  def ReportError(self, tag_name, tag_info=None, msg=None):
    # logging.debug("self.error_mgr_mock.ReportError(%s, %s, %s)",
    #               repr(tag_name), repr(tag_info), repr(msg))
    self.ReportErrorForPkgname(
        self.pkgname, tag_name, tag_info, msg=msg)

  def NeedFile(self, full_path, reason):
    """See base class _NeedFile."""
    self._NeedFile(self.pkgname, full_path, reason)

  def NeedPackage(self, needed_pkg, reason):
    """See base class _NeedPackage."""
    self._NeedPackage(self.pkgname, needed_pkg, reason)


class SetCheckInterface(CheckInterfaceBase):
  """To be passed to set checking functions."""

  def __init__(self, osrel, arch, catrel, catalog, pkg_set_files, rest_client):
    super(SetCheckInterface, self).__init__(
      osrel, arch, catrel, catalog, pkg_set_files, rest_client=rest_client)

  def NeedFile(self, pkgname, full_path, reason):
    """See base class _NeedFile."""
    self._NeedFile(pkgname, full_path, reason)

  def NeedPackage(self, pkgname, needed_pkg, reason):
    """See base class _NeedPackage."""
    self._NeedPackage(pkgname, needed_pkg, reason)

  def ReportError(self, pkgname, tag_name, tag_info=None, msg=None):
    # logging.debug("self.error_mgr_mock.ReportError(%s, %s, %s, %s)",
    #               repr(pkgname),
    #               repr(tag_name), repr(tag_info), repr(msg))
    self.ReportErrorForPkgname(pkgname, tag_name, tag_info, msg)


class CheckpkgMessenger(object):
  """Class responsible for passing messages from checks to the user."""
  def __init__(self):
    self.messages = []
    self.one_time_messages = {}
    self.gar_lines = []

  def Message(self, m):
    # logging.debug("self.messenger.Message(%s)", repr(m))
    self.messages.append(m)

  def OneTimeMessage(self, key, m):
    # logging.debug("self.messenger.OneTimeMessage(%s, %s)", repr(key), repr(m))
    if key not in self.one_time_messages:
      self.one_time_messages[key] = m

  def SuggestGarLine(self, m):
    # logging.debug("self.messenger.SuggestGarLine(%s)", repr(m))
    self.gar_lines.append(m)


class CheckpkgManager2(CheckpkgManagerBase):
  """The second incarnation of the checkpkg manager.

  Implements the API to be used by checking functions.

  Its purpose is to reduce the amount of boilerplate code and allow for easier
  unit test writing.
  """

  def __init__(self, *args, **kwargs):
    super(CheckpkgManager2, self).__init__(*args, **kwargs)
    self.checks_registered = False

  def _RegisterIndividualCheck(self, function):
    self.individual_checks.append(function)

  def _RegisterSetCheck(self, function):
    self.set_checks.append(function)

  def _AutoregisterChecks(self):
    """Autodetects all defined checks."""
    logging.debug("CheckpkgManager2._AutoregisterChecks()")
    if self.checks_registered:
      logging.debug("Checks already registered.")
      return
    from lib.python import package_checks
    checkpkg_module = package_checks
    members = dir(checkpkg_module)
    for member_name in members:
      logging.debug("Examining module member: %s", repr(member_name))
      member = getattr(checkpkg_module, member_name)
      if callable(member):
        if member_name.startswith("Check"):
          logging.debug("Registering individual check %s", repr(member_name))
          self._RegisterIndividualCheck(member)
        elif member_name.startswith("SetCheck"):
          logging.debug("Registering set check %s", repr(member_name))
          self._RegisterSetCheck(member)
    self.checks_registered = True

  def _ReportDependencies(self, checkpkg_interface, needed_files, needed_pkgs,
      messenger, declared_deps_by_pkgname):
    """Creates error tags based on needed files.

    Needed files are extracted from the Interface objects.
    """
    # The idea behind reasons is that if two packages are necessary for
    # the same reason, any of these two would be satisfactory.
    # For example:
    # (CSWfoo, /opt/csw/bin/foo, "provides foo support"),
    # (CSWbar, /opt/csw/bin/bar, "provides foo support"),
    # In such case, either of CSWfoo or CSWbar is satisfactory.
    #
    # If the package under examination already depends on any of
    # packages for a single reason, the dependency is considered
    # satisfied.
    reasons_by_pkg_by_pkgname = {}
    pkgs_by_reasons_by_pkgname = {}
    needed_pkgs = copy.deepcopy(needed_pkgs)
    unsatisfied_needed_files = []
    # Resolving files into packages and adding to the common data structure.
    for needed_file in needed_files:
      pkgname, full_path, reason = needed_file
      logging.debug('_ReportDependencies(): processing %r %r %r', pkgname,
                    full_path, reason)
      needed_pkgnames = checkpkg_interface.GetPkgByPath(full_path)
      if needed_pkgnames:
        for needed_pkgname in needed_pkgnames:
          needed_pkg = NeededPackage(pkgname, needed_pkgname, reason)
          logging.debug('Need package %r', needed_pkg)
          needed_pkgs.append(needed_pkg)
      else:
        logging.warning('Did not find packages for %r', full_path)
        unsatisfied_needed_files.append(needed_file)
    for pkgname, needed_pkgname, reason in needed_pkgs:
      reasons_by_pkg_by_pkgname.setdefault(pkgname, {})
      reasons_by_pkg_by_pkgname[pkgname].setdefault(needed_pkgname, [])
      reasons_by_pkg_by_pkgname[pkgname][needed_pkgname].append(reason)
      pkgs_by_reasons_by_pkgname.setdefault(pkgname, {})
      pkgs_by_reasons_by_pkgname[pkgname].setdefault(reason, [])
      pkgs_by_reasons_by_pkgname[pkgname][reason].append(needed_pkgname)
    # We'll reuse ReportMissingDependencies from dependency_checks, but
    # we have to adapt the data structures.
    req_pkgs_reasons_by_pkgname = {}
    for pkgname in pkgs_by_reasons_by_pkgname:
      for reason in pkgs_by_reasons_by_pkgname[pkgname]:
        reason_group = []
        for needed_pkg in pkgs_by_reasons_by_pkgname[pkgname][reason]:
          reason_group.append((needed_pkg, reason))
        req_pkgs_reasons_by_pkgname.setdefault(pkgname, [])
        req_pkgs_reasons_by_pkgname[pkgname].append(reason_group)

    for pkgname in declared_deps_by_pkgname:
      declared_deps = declared_deps_by_pkgname[pkgname]
      req_pkgs_reasons_by_pkgname.setdefault(pkgname, [])
      (missing_deps_reasons_by_pkg,
       surplus_deps,
       missing_dep_groups) = self._ReportMissingDependencies(
           checkpkg_interface, pkgname, declared_deps,
           req_pkgs_reasons_by_pkgname[pkgname])

      namespace = {
          "pkgname": pkgname,
          "missing_deps": missing_deps_reasons_by_pkg,
          "surplus_deps": surplus_deps,
          "orphan_sonames": None,
      }
      t = Template.Template(REPORT_TMPL, searchList=[namespace])
      report = unicode(t)
      if report.strip():
        for line in report.splitlines():
          messenger.Message(line)

      for missing_deps in missing_dep_groups:
        alternatives = False
        prefix = ""
        if len(missing_deps) > 1:
          alternatives = True
          prefix = "  "
        if alternatives:
          messenger.SuggestGarLine("# One of the following:")
        for missing_dep in missing_deps:
          messenger.SuggestGarLine(
              "%sRUNTIME_DEP_PKGS_%s += %s" % (prefix, pkgname, missing_dep))
        if alternatives:
          messenger.SuggestGarLine("# (end of the list of alternative dependencies)")

    # Files that were declared as needed, but we did not find any packages
    # providing these files.
    for unsatisfied_file in unsatisfied_needed_files:
      # We need to ass a special case for isaexec, because
      # /opt/csw/bin/isaexec in CSWisaexec is created in postinstall, and it
      # isn't present in pkgmap, so it looks like the file is missing.
      if unsatisfied_file.full_path == '/opt/csw/bin/isaexec':
        continue
      checkpkg_interface.ReportErrorForPkgname(
          unsatisfied_file.pkgname,
          'file-needed-but-no-package-satisfies-it',
          '%s %s' % (unsatisfied_file.full_path, unsatisfied_file.reason))

  def _ReportMissingDependencies(self,
                                 error_mgr,
                                 pkgname,
                                 declared_deps,
                                 req_pkgs_reasons):
    """Processes data structures with dependency data and reports errors.

    Processes data specific to a single package.

    Args:
      error_mgr: SetCheckInterface
      pkgname: pkgname, a string
      declared_deps: An iterable with declared dependencies
      req_pkgs_reasons: Groups of reasons

    data structure:
      [
        [
          ("CSWfoo1", "reason"),
          ("CSWfoo2", "reason"),
        ],
        [
          ( ... ),
        ]
      ]
    """
    # Disabling the logging, because pprint.pformat can take an awful lot of
    # time.
    # logging.debug("_ReportMissingDependencies(error_mgr, %s, %s, %s)",
    #     pkgname, declared_deps, pprint.pformat(req_pkgs_reasons))
    missing_reasons_by_pkg = {}
    for reason_group in req_pkgs_reasons:
      for pkg, reason in reason_group:
        missing_reasons_by_pkg.setdefault(pkg, [])
        missing_reasons_by_pkg[pkg].append(reason)
    missing_dep_groups = self._MissingDepsFromReasonGroups(
        pkgname, req_pkgs_reasons, declared_deps)
    missing_dep_groups = self._RemovePkgsFromMissing(pkgname, missing_dep_groups)
    potential_req_pkgs = set(
        (x for x, y in reduce(operator.add, req_pkgs_reasons, [])))
    surplus_deps = self._GetSurplusDeps(pkgname, potential_req_pkgs, declared_deps)
    # Using an index to avoid duplicated reasons.
    missing_deps_reasons_by_pkg = []
    missing_deps_idx = set()
    for missing_deps in missing_dep_groups:
      error_mgr.ReportErrorForPkgname(
          pkgname, "missing-dependency", " or ".join(sorted(missing_deps)))
      for missing_dep in missing_deps:
        item = (missing_dep, tuple(missing_reasons_by_pkg[missing_dep]))
        if item not in missing_deps_idx:
          missing_deps_reasons_by_pkg.append(item)
          missing_deps_idx.add(item)
    for surplus_dep in surplus_deps:
      error_mgr.ReportErrorForPkgname(pkgname, "surplus-dependency", surplus_dep)
    return missing_deps_reasons_by_pkg, surplus_deps, missing_dep_groups

  def _MissingDepsFromReasonGroups(self, for_pkgname, reason_groups, declared_deps_set):
    """Any package from the group satisfies the dependency."""
    missing_dep_groups = []
    for reason_group in reason_groups:
      dependency_fulfilled = False
      for pkgname, reason in reason_group:
        # If one of the packages suggested is the package under examination,
        # consider the dependency satisifed.
        if pkgname == for_pkgname or pkgname in declared_deps_set:
          logging.debug("%r is satisfied by %s", reason, pkgname)
          dependency_fulfilled = True
          break
      if not dependency_fulfilled:
        pkgnames = [x for x, y in reason_group]
        missing_dep_groups.append(pkgnames)
    return missing_dep_groups

  def _GetSurplusDeps(self, pkgname, potential_req_pkgs, declared_deps):
    logging.debug("GetSurplusDeps(%s, potential_req_pkgs=%s, declared_deps=%s)",
                  pkgname, declared_deps, potential_req_pkgs)
    # Surplus dependencies
    # In actual use, there should always be some potential dependencies.
    # assert potential_req_pkgs, "There should be some potential deps!"
    surplus_deps = declared_deps.difference(potential_req_pkgs)
    no_report_surplus = set()
    for sp_regex in common_constants.DO_NOT_REPORT_SURPLUS:
      for maybe_surplus in surplus_deps:
        if re.match(sp_regex, maybe_surplus):
          logging.debug(
              "GetSurplusDeps(): Not reporting %s as surplus because it matches %s.",
              maybe_surplus, sp_regex)
          no_report_surplus.add(maybe_surplus)
    surplus_deps = surplus_deps.difference(no_report_surplus)
    # For some packages (such as dev packages) we don't report surplus deps at
    # all.
    if surplus_deps:
      for regex_str in common_constants.DO_NOT_REPORT_SURPLUS_FOR:
        if re.match(regex_str, pkgname):
          logging.debug(
              "GetSurplusDeps(): Not reporting any surplus because "
              "it matches %s", regex_str)
          surplus_deps = frozenset()
          break
    return surplus_deps

  def _RemovePkgsFromMissing(self, pkgname, missing_dep_groups):
    "Removes packages from the list of missing deps."
    pkgs_to_remove = set()
    missing_deps_flat = set(reduce(operator.add, missing_dep_groups, []))
    for regex_str in common_constants.DO_NOT_REPORT_MISSING_RE:
      regex = re.compile(regex_str)
      for dep_pkgname in missing_deps_flat:
        if re.match(regex, dep_pkgname):
          pkgs_to_remove.add(dep_pkgname)

    # Some packages might have suggestions to depend on themselves, e.g.
    # CSWpython contains .py files, and checkpkg would suggest that it should
    # depend on itself, if not for the following two lines of code.
    if pkgname in missing_deps_flat:
      pkgs_to_remove.add(pkgname)

    logging.debug("Removing %s from the list of missing pkgs.", pkgs_to_remove)
    new_missing_dep_groups = set()
    for missing_deps_group in missing_dep_groups:
      new_missing_deps_group = set()
      for dep in missing_deps_group:
        if dep not in pkgs_to_remove:
          new_missing_deps_group.add(dep)
      if new_missing_deps_group:
        new_missing_dep_groups.add(frozenset(new_missing_deps_group))
    return new_missing_dep_groups

  def _ExaminedFilesByPkg(self, pkgs_data):
    examined_files_by_pkg = {}
    for pkg_data in pkgs_data:
      pkgname = pkg_data["basic_stats"]["pkgname"]
      examined_files_by_pkg.setdefault(pkgname, set())
      for entry in pkg_data["pkgmap"]:
        entry = representations.PkgmapEntry._make(entry)
        if entry.path:
          base_path, base_name = os.path.split(entry.path)
          examined_files_by_pkg[pkgname].add((base_path, base_name))
    return examined_files_by_pkg


  def GetAllTags(self, stats_obj_list):
    errors = {}
    catalog = Catalog()
    logging.debug("Loading all package statistics.")
    pkgs_data = self.GetOptimizedAllStats(stats_obj_list)
    logging.debug("All package statistics loaded.")
    messenger = CheckpkgMessenger()
    # Individual checks
    count = itertools.count()
    pbar = self.GetProgressBar()
    pbar.maxval = len(pkgs_data) * len(self.individual_checks)
    logging.info("Tasting candies one by one...")
    needed_files = []
    needed_pkgs = []
    pbar.start()
    declared_deps_by_pkgname = {}
    # Build a map between packages and files:
    examined_files_by_pkg = self._ExaminedFilesByPkg(pkgs_data)
    # Running individual checks
    for pkg_data in pkgs_data:
      pkgname = pkg_data["basic_stats"]["pkgname"]
      check_interface = IndividualCheckInterface(
          pkgname, self.osrel, self.arch, self.catrel, catalog, examined_files_by_pkg,
          rest_client=self.rest_client)
      for function in self.individual_checks:
        logger = logging.getLogger("%s-%s" % (pkgname, function.__name__))
        logger.debug("Calling %s", function.__name__)
        function(pkg_data, check_interface, logger=logger, messenger=messenger)
        pbar.update(count.next())
      if check_interface.errors:
        errors[pkgname] = check_interface.errors
      # Some sanity checking
      for needed_file in check_interface.needed_files:
        assert pkgname == needed_file.pkgname, (
            "%s reports an error for %s, it shouldn't" % (pkgname,
              needed_file.pkgname))
      for needed_pkg in check_interface.needed_pkgs:
        assert pkgname == needed_pkg.pkgname, (
            "%s reports an error for %s, it shouldn't" % (pkgname,
              needed_pkg.pkgname))
      needed_files.extend(check_interface.needed_files)
      needed_pkgs.extend(check_interface.needed_pkgs)
      # Ideally, this class wouldn't know anything about these data
      # structures, but I don't see a better place for it at the moment.
      declared_deps_by_pkgname[pkgname] = frozenset(x[0] for x in pkg_data["depends"])
    pbar.finish()
    # Set checks
    logging.info("Tasting them all at once...")
    for function in self.set_checks:
      logger = logging.getLogger(function.__name__)
      check_interface = SetCheckInterface(
          self.osrel, self.arch, self.catrel, catalog, examined_files_by_pkg,
          rest_client=self.rest_client)
      logger.debug("Calling %s", function.__name__)
      function(pkgs_data, check_interface, logger=logger, messenger=messenger)
      if check_interface.errors:
        errors = self.SetErrorsToDict(check_interface.errors, errors)
      needed_files.extend(check_interface.needed_files)
      needed_pkgs.extend(check_interface.needed_pkgs)
    check_interface = SetCheckInterface(
        self.osrel, self.arch, self.catrel, catalog, examined_files_by_pkg,
        rest_client=self.rest_client)
    self._ReportDependencies(check_interface,
        needed_files, needed_pkgs, messenger, declared_deps_by_pkgname)
    errors = self.SetErrorsToDict(check_interface.errors, errors)
    messages = messenger.messages + messenger.one_time_messages.values()
    return errors, messages, messenger.gar_lines

  def Run(self):
    self._AutoregisterChecks()
    return super(CheckpkgManager2, self).Run()


def SliceList(l, size):
  """Trasforms a list into a list of lists."""
  idxes = xrange(0, len(l), size)
  sliced = [l[i:i+size] for i in idxes]
  return sliced


class Catalog(SqlobjectHelperMixin):
  """Responsible for functionality related to catalog operations.

  These include:
    - getting a list of all packages
    - getting a list of packages that contain certain files
    - getting a list of packages that contain files of certain names
  """

  def __init__(self):
    super(Catalog, self).__init__()
    self.pkgs_by_path_cache = {}

  def GetInstalledPackages(self, osrel, arch, catrel):
    sqo_osrel, sqo_arch, sqo_catrel = self.GetSqlobjectTriad(
        osrel, arch, catrel)
    logging.debug("GetInstalledPackages(%s, %s, %s)"
                  % (osrel, arch, catrel))

    # Object defining a filter for our OS release, architecture and catalog
    # release.
    oac = sqlobject.AND(
              m.Srv4FileInCatalog.q.osrel==sqo_osrel,
              m.Srv4FileInCatalog.q.arch==sqo_arch,
              m.Srv4FileInCatalog.q.catrel==sqo_catrel)
    # Join object, responsible for connecting the tables the right way.
    join = [
        sqlbuilder.INNERJOINOn(None,
          m.Srv4FileStats,
          m.Pkginst.q.id==m.Srv4FileStats.q.pkginst),
        sqlbuilder.INNERJOINOn(None,
          m.Srv4FileInCatalog,
          m.Srv4FileStats.q.id==m.Srv4FileInCatalog.q.srv4file),
        ]

    res = m.Pkginst.select(oac, join=join)
    pkgs = [x.pkgname for x in res]
    return pkgs

  def GetPathsAndPkgnamesByBasename(self, basename, osrel, arch, catrel):
    """Retrieves pkginst names of packages that have certain files.

    Since it needs to match a specific catalog, a table join is required:
      - CswFile (basename)
      - related Srv4FileStats
      - related Srv4FileInCatalog

    Args:
      basename: u'libfoo.so.1'
      osrel: u'5.9'
      arch: 'sparc', 'x86'
      catrel: 'stable'

    Returns:
      {"/opt/csw/lib": ["CSWfoo", "CSWbar"],
       "/opt/csw/1/lib": ["CSWfoomore"]}
    """
    pkgs = {}
    sqo_osrel, sqo_arch, sqo_catrel = self.GetSqlobjectTriad(
        osrel, arch, catrel)

    connection = m.CswFile._connection
    join = [
        sqlbuilder.INNERJOINOn(None,
          m.Pkginst,
          m.CswFile.q.pkginst==m.Pkginst.q.id),
        sqlbuilder.INNERJOINOn(None,
          m.Srv4FileStats,
          m.CswFile.q.srv4_file==m.Srv4FileStats.q.id),
        sqlbuilder.INNERJOINOn(None,
          m.Srv4FileInCatalog,
          m.Srv4FileStats.q.id==m.Srv4FileInCatalog.q.srv4file),
    ]
    where = sqlobject.AND(
        m.CswFile.q.basename==basename,
        m.Srv4FileInCatalog.q.osrel==sqo_osrel,
        m.Srv4FileInCatalog.q.arch==sqo_arch,
        m.Srv4FileInCatalog.q.catrel==sqo_catrel,
    )
    query = connection.sqlrepr(
        sqlbuilder.Select(
          [m.CswFile.q.path, m.Pkginst.q.pkgname],
          where=where,
          join=join))
    rows = connection.queryAll(query)
    pkgs = {}

    for row in rows:
      file_path, pkginst = row
      pkgs.setdefault(file_path, []).append(pkginst)

    logging.debug("self.error_mgr_mock.GetPathsAndPkgnamesByBasename(%s)"
                  ".AndReturn(%s)", repr(basename), pprint.pformat(pkgs))
    return pkgs


  def GetPathsAndPkgnamesByBasedir(self, basedir, osrel, arch, catrel):
    sqo_osrel, sqo_arch, sqo_catrel = self.GetSqlobjectTriad(
        osrel, arch, catrel)
    connection = m.CswFile._connection
    join = [
        sqlbuilder.INNERJOINOn(None,
          m.Pkginst,
          m.CswFile.q.pkginst==m.Pkginst.q.id),
        sqlbuilder.INNERJOINOn(None,
          m.Srv4FileStats,
          m.CswFile.q.srv4_file==m.Srv4FileStats.q.id),
        sqlbuilder.INNERJOINOn(None,
          m.Srv4FileInCatalog,
          m.Srv4FileStats.q.id==m.Srv4FileInCatalog.q.srv4file),
    ]
    where = sqlobject.AND(
        m.CswFile.q.path==basedir,
        m.Srv4FileInCatalog.q.osrel==sqo_osrel,
        m.Srv4FileInCatalog.q.arch==sqo_arch,
        m.Srv4FileInCatalog.q.catrel==sqo_catrel,
    )
    query = connection.sqlrepr(
        sqlbuilder.Select(
          [m.CswFile.q.basename, m.Pkginst.q.pkgname],
          where=where,
          join=join))
    rows = connection.queryAll(query)
    pkgs = {}
    for row in rows:
      basename, pkginst = row
      pkgs.setdefault(pkginst, []).append(basename)
    return pkgs

  def GetPkgByPath(self, full_file_path, osrel, arch, catrel):
    """Returns a list of packages."""
    # TODO(maciej): Move this to models.py and have pkgdb_web return the JSON
    # structure. This is a step towards RESTification.
    key = (full_file_path, osrel, arch, catrel)
    if key not in self.pkgs_by_path_cache:
      file_path, basename = os.path.split(full_file_path)
      sqo_osrel, sqo_arch, sqo_catrel = self.GetSqlobjectTriad(
          osrel, arch, catrel)
      oac = sqlobject.AND(
          m.Srv4FileInCatalog.q.osrel==sqo_osrel,
          m.Srv4FileInCatalog.q.arch==sqo_arch,
          m.Srv4FileInCatalog.q.catrel==sqo_catrel)
      path_filter = sqlobject.AND(
          oac,
          m.CswFile.q.path==file_path,
          m.CswFile.q.basename==basename,
          m.Srv4FileStats.q.registered_level_two==True)
      join = [
          sqlbuilder.INNERJOINOn(None,
            m.Srv4FileStats,
            m.Pkginst.q.id==m.Srv4FileStats.q.pkginst),
          sqlbuilder.INNERJOINOn(None,
            m.Srv4FileInCatalog,
            m.Srv4FileStats.q.id==m.Srv4FileInCatalog.q.srv4file),
          sqlbuilder.INNERJOINOn(None,
            m.CswFile,
            m.Srv4FileStats.q.id==m.CswFile.q.srv4_file),
          ]
      res = m.Pkginst.select(path_filter, join=join)
      pkgs = [x.pkgname for x in res]
      self.pkgs_by_path_cache[key] = frozenset(pkgs)
    return self.pkgs_by_path_cache[key]

  def CommonArchByString(self, s):
    return sharedlib_utils.ArchByString(s)

  def Srv4MatchesCatalog(self, sqo_srv4, sqo_arch):
    cat_arch = self.CommonArchByString(sqo_arch.name)
    pkg_arch = self.CommonArchByString(sqo_srv4.arch.name)
    ans = (cat_arch == pkg_arch) or (pkg_arch == common_constants.ARCH_ALL)
    if not ans:
      logging.debug("Srv4MatchesCatalog(): mismatch: %s / %s and %s / %s",
                    cat_arch, pkg_arch, pkg_arch, common_constants.ARCH_ALL)
      # Some packages have the architecture in the file saying 'all', but pkginfo
      # says 'i386'.
      filename_arch = self.CommonArchByString(sqo_srv4.filename_arch.name)
      if filename_arch == common_constants.ARCH_ALL:
        ans = True
      if filename_arch != pkg_arch:
        logging.warning(
            "Package %s declares %s in pkginfo and %s in the filename.",
            sqo_srv4, repr(pkg_arch), repr(filename_arch))
    return ans

  def GetConflictingSrv4ByCatalognameResult(self,
      sqo_srv4, catalogname,
      sqo_osrel, sqo_arch, sqo_catrel):
    res = m.Srv4FileStats.select(
            m.Srv4FileStats.q.catalogname==catalogname
            ).throughTo.in_catalogs.filter(
                sqlobject.AND(
                  m.Srv4FileInCatalog.q.osrel==sqo_osrel,
                  m.Srv4FileInCatalog.q.arch==sqo_arch,
                  m.Srv4FileInCatalog.q.catrel==sqo_catrel,
                  m.Srv4FileInCatalog.q.srv4file!=sqo_srv4))
    return res

  def GetConflictingSrv4ByPkgnameResult(self,
      sqo_srv4, pkgname,
      sqo_osrel, sqo_arch, sqo_catrel):
    join = [
        sqlbuilder.INNERJOINOn(None,
          m.Pkginst,
          m.Srv4FileStats.q.pkginst==m.Pkginst.q.id),
    ]
    res = m.Srv4FileStats.select(
            m.Pkginst.q.pkgname==pkgname,
            join=join
            ).throughTo.in_catalogs.filter(
                sqlobject.AND(
                  m.Srv4FileInCatalog.q.osrel==sqo_osrel,
                  m.Srv4FileInCatalog.q.arch==sqo_arch,
                  m.Srv4FileInCatalog.q.catrel==sqo_catrel,
                  m.Srv4FileInCatalog.q.srv4file!=sqo_srv4))
    return res

  def AddSrv4ToCatalog(self, sqo_srv4, osrel, arch, catrel, who=None):
    """Registers a srv4 file in a catalog."""
    logging.debug("AddSrv4ToCatalog(%s, %s, %s, %s, %s)",
        sqo_srv4, osrel, arch, catrel, who)
    if not who:
      who = 'unknown'
    # There are only i386 and sparc catalogs.
    if arch not in ('i386', 'sparc'):
      raise CatalogDatabaseError("Wrong architecture: %s" % arch)
    sqo_osrel, sqo_arch, sqo_catrel = self.GetSqlobjectTriad(
        osrel, arch, catrel)
    if not self.Srv4MatchesCatalog(sqo_srv4, sqo_arch):
      raise CatalogDatabaseError(
          "Specified package does not match the catalog. "
          "Package: %s, catalog: %s %s %s"
          % (sqo_srv4, osrel, arch, catrel))
    if not sqo_srv4.registered_level_two:
      raise CatalogDatabaseError(
          "Package %s (%s) is not registered for releases."
          % (sqo_srv4.basename, sqo_srv4.md5_sum))
    # TODO(maciej): Make sure the package's files are present in the database.
    # Checking for presence of a different srv4 with the same pkginst in the
    # same catalog
    pkginst = sqo_srv4.pkginst
    res = m.Srv4FileStats.select(
            m.Srv4FileStats.q.pkginst==pkginst).throughTo.in_catalogs.filter(
                sqlobject.AND(
                  m.Srv4FileInCatalog.q.osrel==sqo_osrel,
                  m.Srv4FileInCatalog.q.arch==sqo_arch,
                  m.Srv4FileInCatalog.q.catrel==sqo_catrel,
                  m.Srv4FileInCatalog.q.srv4file!=sqo_srv4))
    if res.count():
      raise CatalogDatabaseError(
          "There already is a package with that pkgname: %s" % pkginst.pkgname)
    res = self.GetConflictingSrv4ByCatalognameResult(
        sqo_srv4, sqo_srv4.catalogname,
        sqo_osrel, sqo_arch, sqo_catrel)
    if res.count():
      raise CatalogDatabaseError(
          "There already is a package with that catalogname: %s"
          % sqo_srv4.catalogname)
    # Checking for presence of the same srv4 already in the catalog.
    res = m.Srv4FileInCatalog.select(
        sqlobject.AND(
            m.Srv4FileInCatalog.q.osrel==sqo_osrel,
            m.Srv4FileInCatalog.q.arch==sqo_arch,
            m.Srv4FileInCatalog.q.catrel==sqo_catrel,
            m.Srv4FileInCatalog.q.srv4file==sqo_srv4))
    if res.count():
      logging.debug("%s is already part of %s %s %s",
                      sqo_srv4, osrel, arch, catrel)
      # Our srv4 is already part of that catalog.
      return
    # SQL INSERT happens here.
    m.Srv4FileInCatalog(
        arch=sqo_arch,
        osrel=sqo_osrel,
        catrel=sqo_catrel,
        srv4file=sqo_srv4,
        created_by=who)
    # The package is now in the catalog.

  def RemoveSrv4(self, sqo_srv4, osrel, arch, catrel):
    sqo_osrel, sqo_arch, sqo_catrel = self.GetSqlobjectTriad(
        osrel, arch, catrel)
    try:
      # There's a race condition in here. Maybe SQLObject allows to delete atomically?
      sqo_srv4_in_cat = m.Srv4FileInCatalog.select(
          sqlobject.AND(
            m.Srv4FileInCatalog.q.arch==sqo_arch,
            m.Srv4FileInCatalog.q.osrel==sqo_osrel,
            m.Srv4FileInCatalog.q.catrel==sqo_catrel,
            m.Srv4FileInCatalog.q.srv4file==sqo_srv4)).getOne()
      # Files belonging to this package should not be removed from the catalog
      # as the package might be still present in another catalog.
      sqo_srv4_in_cat.destroySelf()
    except sqlobject.main.SQLObjectNotFound as e:
      logging.warning(e)
