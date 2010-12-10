# A collection of checkpkg-specific classes.
#
# This file is supposed to drain the checkpkg.py file until is becomes
# empty and goes away.

import copy
from Cheetah import Template
import logging
import package_stats
import package_checks
import sqlobject
import itertools
import progressbar
import database
import models as m
import textwrap
import os.path
import tag
import pprint
import operator
import common_constants
import sharedlib_utils
import mute_progressbar
import cPickle


class Error(Exception):
  pass


class CatalogDatabaseError(Error):
  pass


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


class SqlobjectHelperMixin(object):

  def GetSqlobjectTriad(self, osrel, arch, catrel):
    logging.debug("GetSqlobjectTriad(%s,  %s,  %s)", osrel, arch, catrel)
    sqo_arch = m.Architecture.select(
        m.Architecture.q.name==arch).getOne()
    sqo_osrel = m.OsRelease.select(
        m.OsRelease.q.short_name==osrel).getOne()
    sqo_catrel = m.CatalogRelease.select(
        m.CatalogRelease.q.name==catrel).getOne()
    return sqo_osrel, sqo_arch, sqo_catrel


class CheckpkgManagerBase(SqlobjectHelperMixin):
  """Common functions between the older and newer calling functions."""

  def __init__(self, name, sqo_pkgs_list, osrel, arch, catrel, debug=False,
      show_progress=False):
    self.debug = debug
    self.name = name
    self.sqo_pkgs_list = sqo_pkgs_list
    self.errors = []
    self.individual_checks = []
    self.set_checks = []
    self.packages = []
    self.osrel = osrel
    self.arch = arch
    self.catrel = catrel
    self.show_progress = show_progress

  def GetProgressBar(self):
    if self.show_progress:
      return progressbar.ProgressBar()
    else:
      return mute_progressbar.MuteProgressBar()

  def GetSqlobjectTriad(self):
     return super(CheckpkgManagerBase, self).GetSqlobjectTriad(
         self.osrel, self.arch, self.catrel)

  def GetPackageStatsList(self):
    raise RuntimeError("Please don't use this function as it violates "
                       "the Law of Demeter.")

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
      i = counter.next()
      raw_pkg_data = cPickle.loads(stats_obj.data_obj.pickle)
      pkg_data = raw_pkg_data
      pkgs_data.append(pkg_data)
      pbar.update(i)
    pbar.finish()
    return pkgs_data

  def Run(self):
    """Runs all the checks

    Returns a tuple of an exit code and a report.
    """
    # packages_data = self.GetPackageStatsList()
    assert self.sqo_pkgs_list, "The list of packages must not be empty."
    db_stat_objs_by_pkgname = {}
    for pkg in self.sqo_pkgs_list:
      db_stat_objs_by_pkgname[pkg.pkginst.pkgname] = pkg
    logging.debug("Deleting old errors from the database.")
    for pkgname, db_obj in db_stat_objs_by_pkgname.iteritems():
      sqo_os_rel, sqo_arch, sqo_catrel = self.GetSqlobjectTriad()
      db_obj.RemoveCheckpkgResults(
          sqo_os_rel, sqo_arch, sqo_catrel)
    errors, messages, gar_lines = self.GetAllTags(self.sqo_pkgs_list)
    no_errors = len(errors) + 1
    pbar = self.GetProgressBar()
    pbar.maxval = no_errors
    count = itertools.count(1)
    logging.info("Stuffing the candies under the pillow...")
    pbar.start()
    for pkgname, es in errors.iteritems():
      logging.debug("Saving errors of %s to the database.", pkgname)
      for e in es:
        if e.pkgname not in db_stat_objs_by_pkgname:
          logging.warning("Not saving an error for %s.", e.pkgname)
          continue
        db_error = m.CheckpkgErrorTag(srv4_file=db_stat_objs_by_pkgname[e.pkgname],
                                      pkgname=e.pkgname,
                                      tag_name=e.tag_name,
                                      tag_info=e.tag_info,
                                      msg=e.msg,
                                      os_rel=sqo_os_rel,
                                      catrel=sqo_catrel,
                                      arch=sqo_arch)
      pbar.update(count.next())
    pbar.finish()
    flat_error_list = reduce(operator.add, errors.values(), [])
    screen_report, tags_report = self.FormatReports(errors, messages, gar_lines)
    exit_code = 0
    return (exit_code, screen_report, tags_report)


class CheckInterfaceBase(object):
  """Provides an interface for checking functions.

  It wraps access to the catalog database.
  """

  def __init__(self, osrel, arch, catrel, catalog=None, lines_dict=None):
    self.osrel = osrel
    self.arch = arch
    self.catrel = catrel
    self.catalog = catalog
    if not self.catalog:
      self.catalog = Catalog()
    self.common_paths = {}
    if lines_dict:
      self.lines_dict = lines_dict
    else:
      self.lines_dict = {}

  def GetPathsAndPkgnamesByBasename(self, basename):
    """Proxies calls to class member."""
    return self.catalog.GetPathsAndPkgnamesByBasename(
        basename, self.osrel, self.arch, self.catrel)

  def GetPkgByPath(self, file_path):
    """Proxies calls to self.system_pkgmap."""
    return self.catalog.GetPkgByPath(
        file_path, self.osrel, self.arch, self.catrel)

  def GetInstalledPackages(self):
    return self.catalog.GetInstalledPackages(
        self.osrel, self.arch, self.catrel)

  def _GetPathsForArch(self, arch):
    if not arch in self.lines_dict:
      file_name = os.path.join(
          os.path.dirname(__file__), "..", "..", "etc", "commondirs-%s" % arch)
      logging.debug("opening %s", file_name)
      f = open(file_name, "r")
      self.lines_dict[arch] = f.read().splitlines()
      f.close()
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


class IndividualCheckInterface(CheckInterfaceBase):
  """To be passed to the checking functions.

  Wraps the creation of tag.CheckpkgTag objects.
  """

  def __init__(self, pkgname, osrel, arch, catrel, catalog=None):
    super(IndividualCheckInterface, self).__init__(osrel, arch, catrel, catalog)
    self.pkgname = pkgname
    self.errors = []

  def ReportError(self, tag_name, tag_info=None, msg=None):
    logging.debug("self.error_mgr_mock.ReportError(%s, %s, %s)",
                  repr(tag_name), repr(tag_info), repr(msg))
    checkpkg_tag = tag.CheckpkgTag(self.pkgname, tag_name, tag_info, msg=msg)
    self.errors.append(checkpkg_tag)


class SetCheckInterface(CheckInterfaceBase):
  """To be passed to set checking functions."""

  def __init__(self, osrel, arch, catrel, catalog=None):
    super(SetCheckInterface, self).__init__(osrel, arch, catrel, catalog)
    self.errors = []

  def ReportError(self, pkgname, tag_name, tag_info=None, msg=None):
    logging.debug("self.error_mgr_mock.ReportError(%s, %s, %s, %s)",
                  repr(pkgname),
                  repr(tag_name), repr(tag_info), repr(msg))
    checkpkg_tag = tag.CheckpkgTag(pkgname, tag_name, tag_info, msg=msg)
    self.errors.append(checkpkg_tag)


class CheckpkgMessenger(object):
  """Class responsible for passing messages from checks to the user."""
  def __init__(self):
    self.messages = []
    self.one_time_messages = {}
    self.gar_lines = []

  def Message(self, m):
    logging.debug("self.messenger.Message(%s)", repr(m))
    self.messages.append(m)

  def OneTimeMessage(self, key, m):
    logging.debug("self.messenger.OneTimeMessage(%s, %s)", repr(key), repr(m))
    if key not in self.one_time_messages:
      self.one_time_messages[key] = m

  def SuggestGarLine(self, m):
    logging.debug("self.messenger.SuggestGarLine(%s)", repr(m))
    self.gar_lines.append(m)


class CheckpkgManager2(CheckpkgManagerBase):
  """The second incarnation of the checkpkg manager.

  Implements the API to be used by checking functions.

  Its purpose is to reduce the amount of boilerplate code and allow for easier
  unit test writing.
  """
  def _RegisterIndividualCheck(self, function):
    self.individual_checks.append(function)

  def _RegisterSetCheck(self, function):
    self.set_checks.append(function)

  def _AutoregisterChecks(self):
    """Autodetects all defined checks."""
    logging.debug("CheckpkgManager2._AutoregisterChecks()")
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
    pbar.start()
    for pkg_data in pkgs_data:
      pkgname = pkg_data["basic_stats"]["pkgname"]
      check_interface = IndividualCheckInterface(
          pkgname, self.osrel, self.arch, self.catrel, catalog)
      for function in self.individual_checks:
        logger = logging.getLogger("%s-%s" % (pkgname, function.__name__))
        logger.debug("Calling %s", function.__name__)
        function(pkg_data, check_interface, logger=logger, messenger=messenger)
        if check_interface.errors:
          errors[pkgname] = check_interface.errors
        pbar.update(count.next())
    pbar.finish()
    # Set checks
    logging.info("Tasting them all at once...")
    for function in self.set_checks:
      logger = logging.getLogger(function.__name__)
      check_interface = SetCheckInterface(
          self.osrel, self.arch, self.catrel, catalog)
      logger.debug("Calling %s", function.__name__)
      function(pkgs_data, check_interface, logger=logger, messenger=messenger)
      if check_interface.errors:
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


class CatalogMixin(SqlobjectHelperMixin):
  """Responsible for functionality related to catalog operations.

  These include:
    - getting a list of all packages
    - getting a list of packages that contain certain files
    - getting a list of packages that contain files of certain names
  """

  def __init__(self):
    super(CatalogMixin, self).__init__()
    self.pkgs_by_path_cache = {}

  def GetInstalledPackages(self, osrel, arch, catrel):
    sqo_osrel, sqo_arch, sqo_catrel = self.GetSqlobjectTriad(
        osrel, arch, catrel)
    res = m.Srv4FileInCatalog.select(
        sqlobject.AND(
          m.Srv4FileInCatalog.q.osrel==sqo_osrel,
          m.Srv4FileInCatalog.q.arch==sqo_arch,
          m.Srv4FileInCatalog.q.catrel==sqo_catrel))
    pkgs = []
    for srv4_in_cat in res:
      pkgs.append(srv4_in_cat.srv4file.pkginst.pkgname)
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

    # Looks like this join is hard to do that way.
    # res = m.Srv4FileInCatalog.select(
    #           sqlobject.AND(
    #               m.Srv4FileInCatalog.q.osrel==sqo_osrel,
    #               m.Srv4FileInCatalog.q.arch==sqo_arch,
    #               m.Srv4FileInCatalog.q.catrel==sqo_catrel)).
    #           throughTo.srv4file.thoughTo.files

    # We'll implement it on the application level.  First, we'll get all
    # the files that match the basename, and then filter them based on
    # catalog properties.
    res = m.CswFile.select(m.CswFile.q.basename==basename)
    file_list = []
    for f in res:
      # Check whether osrel, arch and catrel are matching.
      for cat in f.srv4_file.in_catalogs:
        if (f.srv4_file.registered
            and cat.osrel == sqo_osrel
            and cat.arch == sqo_arch
            and cat.catrel == sqo_catrel):
          file_list.append(f)
    for obj in file_list:
      pkgs.setdefault(obj.path, [])
      pkgs[obj.path].append(obj.pkginst.pkgname)
    logging.debug("self.error_mgr_mock.GetPathsAndPkgnamesByBasename(%s)"
                  ".AndReturn(%s)", repr(basename), pprint.pformat(pkgs))
    return pkgs

  def GetPkgByPath(self, full_file_path, osrel, arch, catrel):
    """Returns a list of packages."""
    # Memoization for performance
    key = (full_file_path, osrel, arch, catrel)
    if key not in self.pkgs_by_path_cache:
      pkgs = []
      file_path, basename = os.path.split(full_file_path)
      sqo_osrel, sqo_arch, sqo_catrel = self.GetSqlobjectTriad(
          osrel, arch, catrel)
      res = m.CswFile.select(
          sqlobject.AND(
            m.CswFile.q.path==file_path,
            m.CswFile.q.basename==basename))
      for sqo_file in res:
        # Making sure that we're taking packages only from the right catalog.
        for cat in sqo_file.srv4_file.in_catalogs:
          if (sqo_file.srv4_file.registered
              and cat.osrel == sqo_osrel
              and cat.arch == sqo_arch
              and cat.catrel == sqo_catrel):
            pkgs.append(sqo_file.srv4_file.pkginst.pkgname)
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

  def AddSrv4ToCatalog(self, sqo_srv4, osrel, arch, catrel):
    """Registers a srv4 file in a catalog."""
    logging.debug("AddSrv4ToCatalog(%s, %s, %s, %s)",
        sqo_srv4, osrel, arch, catrel)
    sqo_osrel, sqo_arch, sqo_catrel = self.GetSqlobjectTriad(
        osrel, arch, catrel)
    if not self.Srv4MatchesCatalog(sqo_srv4, sqo_arch):
      raise CatalogDatabaseError(
          "Specified package does not match the catalog. "
          "Package: %s, catalog: %s %s %s"
          % (sqo_srv4, osrel, arch, catrel))
    if not sqo_srv4.registered:
      raise CatalogDatabaseError(
          "Package %s (%s) is not registered for releases."
          % (sqo_srv4.basename, sqo_srv4.md5_sum))
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
    if len(list(res)):
      raise CatalogDatabaseError(
          "There already is a package with that pkgname: %s" % pkginst)
    # Checking for presence of the same srv4 already in the catalog.
    res = m.Srv4FileInCatalog.select(
        sqlobject.AND(
            m.Srv4FileInCatalog.q.osrel==sqo_osrel,
            m.Srv4FileInCatalog.q.arch==sqo_arch,
            m.Srv4FileInCatalog.q.catrel==sqo_catrel,
            m.Srv4FileInCatalog.q.srv4file==sqo_srv4))
    if len(list(res)):
      logging.debug("%s is already part of %s %s %s",
                    sqo_srv4, osrel, arch, catrel)
      # Our srv4 is already part of that catalog.
      return
    obj = m.Srv4FileInCatalog(
        arch=sqo_arch,
        osrel=sqo_osrel,
        catrel=sqo_catrel,
        srv4file=sqo_srv4)

  def RemoveSrv4(self, sqo_srv4, osrel, arch, catrel):
    sqo_osrel, sqo_arch, sqo_catrel = self.GetSqlobjectTriad(
        osrel, arch, catrel)
    sqo_srv4_in_cat = m.Srv4FileInCatalog.select(
        sqlobject.AND(
          m.Srv4FileInCatalog.q.arch==sqo_arch,
          m.Srv4FileInCatalog.q.osrel==sqo_osrel,
          m.Srv4FileInCatalog.q.catrel==sqo_catrel,
          m.Srv4FileInCatalog.q.srv4file==sqo_srv4)).getOne()
    sqo_srv4_in_cat.registered = False
    # TODO(maciej): Remove all files belonging to that one
    for cat_file in sqo_srv4_in_cat.srv4file.files:
      cat_file.destroySelf()


class Catalog(CatalogMixin):
  pass
