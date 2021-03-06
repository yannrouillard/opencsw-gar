#!/usr/bin/env python2.6

# Try to use unittest2, fall back to unittest
try:
  import unittest2 as unittest
except ImportError:
  import unittest

import pprint

import cjson
import copy
import cPickle
import hashlib
import mox
import pprint
import re
import sqlite3
import sqlobject

from lib.python import checkpkg_lib
from lib.python import common_constants
from lib.python import database
from lib.python import models
from lib.python import package_stats
from lib.python import relational_util
from lib.python import tag
from lib.python import rest
from lib.python import test_base
from lib.python.testdata import neon_stats
from lib.python.testdata import stubs
from lib.web import releases_web

class CheckpkgManager2UnitTest(mox.MoxTestBase):

  def testSingleTag(self):
    m = checkpkg_lib.CheckpkgManager2(
            "testname", [], "5.9", "sparc", "unstable")
    tags = {
        "CSWfoo": [
          tag.CheckpkgTag("CSWfoo", "foo-tag", "foo-info"),
        ],
    }
    screen_report, tags_report = m.FormatReports(tags, [], [])
    expected = u'# Tags reported by testname module\nCSWfoo: foo-tag foo-info\n'
    self.assertEqual(expected, unicode(tags_report))

  def testThreeTags(self):
    m = checkpkg_lib.CheckpkgManager2(
            "testname", [], "5.9", "sparc", "unstable")
    tags = {
        "CSWfoo": [
          tag.CheckpkgTag("CSWfoo", "foo-tag", "foo-info"),
          tag.CheckpkgTag("CSWfoo", "bar-tag", "bar-info"),
          tag.CheckpkgTag("CSWfoo", "baz-tag"),
        ],
    }
    screen_report, tags_report = m.FormatReports(tags, [], [])
    expected = (u'# Tags reported by testname module\n'
                u'CSWfoo: foo-tag foo-info\n'
                u'CSWfoo: bar-tag bar-info\n'
                u'CSWfoo: baz-tag\n')
    self.assertEqual(expected, unicode(tags_report))

  def testGetAllTags(self):
    # Does not run any checks, because they are unregistered.  However,
    # needfile and needpkg mechanisms are active.
    #
    # Disabling this check for now, because there are issues with mocking out
    # some of the objects.
    # TODO(maciej): Enable this check again.
    return
    self.mox.StubOutWithMock(checkpkg_lib, 'IndividualCheckInterface',
        use_mock_anything=True)
    self.mox.StubOutWithMock(checkpkg_lib, 'SetCheckInterface',
        use_mock_anything=True)
    # checkpkg_interface_mock = self.mox.CreateMock(
    #     checkpkg_lib.IndividualCheckInterface)
    # Throws:
    # UnknownMethodCallError: Method called is not a member of the
    # object: GetPkgByPath
    checkpkg_interface_mock = self.mox.CreateMockAnything()
    # checkpkg_interface_mock = self.mox.CreateMock(
    #     checkpkg_lib.IndividualCheckInterface)
    set_interface_mock = self.mox.CreateMockAnything()
    # checkpkg_interface_mock.GetPkgByPath("/opt/csw/bin/foo").AndReturn(
    #     ["CSWbar", "CSWbaz"])
    set_interface_mock.errors = []
    set_interface_mock.needed_files = []
    set_interface_mock.needed_pkgs = []
    checkpkg_interface_mock.errors = []
    checkpkg_interface_mock.needed_files = [
        checkpkg_lib.NeededFile("CSWneon", "/opt/csw/bin/foo", "Because!"),
    ]
    checkpkg_interface_mock.needed_pkgs = []
    self.mox.StubOutWithMock(checkpkg_lib, 'Catalog',
        use_mock_anything=True)
    checkpkg_lib.IndividualCheckInterface(
        'CSWneon', '5.9', 'sparc', 'unstable', catalog_mock).AndReturn(
            checkpkg_interface_mock)
    checkpkg_lib.SetCheckInterface(
        'CSWneon', '5.9', 'sparc', 'unstable', catalog_mock).AndReturn(
            set_interface_mock)
    stat_obj = self.mox.CreateMockAnything()
    data_obj = self.mox.CreateMockAnything()
    stat_obj.data_obj = data_obj
    pkg_stats = copy.deepcopy(neon_stats.pkgstats)
    # Resetting the dependencies so that it doesn't report surplus deps.
    pkg_stats["depends"] = []
    data_obj.pickle = cPickle.dumps(pkg_stats)
    checkpkg_interface_mock.ReportErrorForPkgname(
        'CSWneon', 'missing-dependency', 'CSWbar or CSWbaz')
    catalog_mock.GetPkgByPath('/opt/csw/bin/foo', '5.9', 'sparc',
        'unstable').AndReturn(["CSWbar", "CSWbaz"])
    self.mox.ReplayAll()
    m = checkpkg_lib.CheckpkgManager2(
            "testname", [], "5.9", "sparc", "unstable")
    # m._AutoregisterChecks()
    errors, messages, gar_lines = m.GetAllTags([stat_obj])
    self.mox.VerifyAll()
    # self.assertEquals(
    #     {'CSWneon': [tag.CheckpkgTag('CSWneon', 'missing-dependency', 'CSWbar or CSWbaz')]},
    #     errors)
    expected_messages =  [
        u'Dependency issues of CSWneon:',
        u'CSWbar is needed by CSWneon, because:',
        u' - Because!',
        u'RUNTIME_DEP_PKGS_CSWneon += CSWbar',
        u'CSWbaz is needed by CSWneon, because:',
        u' - Because!',
        u'RUNTIME_DEP_PKGS_CSWneon += CSWbaz',
    ]
    self.assertEquals(expected_messages, messages)
    expected_gar_lines = [
        '# One of the following:',
        '  RUNTIME_DEP_PKGS_CSWneon += CSWbar',
        '  RUNTIME_DEP_PKGS_CSWneon += CSWbaz',
        '# (end of the list of alternative dependencies)']
    self.assertEquals(expected_gar_lines, gar_lines)

  def test_ReportDependencies(self):
    m = checkpkg_lib.CheckpkgManager2(
            "testname", [], "5.9", "sparc", "unstable")
    checkpkg_interface_mock = self.mox.CreateMock(
        checkpkg_lib.IndividualCheckInterface)
    needed_files = [
        ("CSWfoo", "/opt/csw/bin/needed_file", "reason1"),
    ]
    needed_pkgs = []
    messenger_stub = stubs.MessengerStub()
    declared_deps_by_pkgname = {
        "CSWfoo": frozenset([
          "CSWbar-1",
          "CSWbar-2",
        ]),
    }
    checkpkg_interface_mock.GetPkgByPath('/opt/csw/bin/needed_file').AndReturn(
        ["CSWfoo-one", "CSWfoo-two"]
    )
    checkpkg_interface_mock.ReportErrorForPkgname(
        'CSWfoo', 'missing-dependency', 'CSWfoo-one or CSWfoo-two')
    checkpkg_interface_mock.ReportErrorForPkgname(
        'CSWfoo', 'surplus-dependency', 'CSWbar-2')
    checkpkg_interface_mock.ReportErrorForPkgname(
        'CSWfoo', 'surplus-dependency', 'CSWbar-1')
    self.mox.ReplayAll()
    m._ReportDependencies(checkpkg_interface_mock,
                          needed_files,
                          needed_pkgs,
                          messenger_stub,
                          declared_deps_by_pkgname)

  def test_ReportDependenciesDirProvidedBySelf(self):
    m = checkpkg_lib.CheckpkgManager2(
            "testname", [], "5.9", "sparc", "unstable")
    checkpkg_interface_mock = self.mox.CreateMock(
        checkpkg_lib.IndividualCheckInterface)
    needed_files = [
        ("CSWfoo", "/opt/csw/share/man/man1m", "reason1"),
    ]
    needed_pkgs = []
    messenger_stub = stubs.MessengerStub()
    declared_deps_by_pkgname = {"CSWfoo": frozenset()}
    checkpkg_interface_mock.GetPkgByPath('/opt/csw/share/man/man1m').AndReturn(
        ["CSWfoo", "CSWfoo-one", "CSWfoo-two"]
    )
    # Should not report any dependencies; the /opt/csw/share/man/man1m path is
    # provided by the package itself.
    self.mox.ReplayAll()
    m._ReportDependencies(checkpkg_interface_mock,
                          needed_files,
                          needed_pkgs,
                          messenger_stub,
                          declared_deps_by_pkgname)

  def testSurplusDeps(self):
    m = checkpkg_lib.CheckpkgManager2(
            "testname", [], "5.9", "sparc", "unstable")
    potential_req_pkgs = set([u"CSWbar"])
    declared_deps = set([u"CSWbar", u"CSWsurplus"])
    expected = set(["CSWsurplus"])
    self.assertEquals(
        expected,
        m._GetSurplusDeps("CSWfoo", potential_req_pkgs, declared_deps))

  def testMissingDepsFromReasonGroups(self):
    m = checkpkg_lib.CheckpkgManager2(
            "testname", [], "5.9", "sparc", "unstable")
    reason_groups = [
        [(u"CSWfoo1", ""),
         (u"CSWfoo2", "")],
        [(u"CSWbar", "")],
    ]
    declared_deps = set([u"CSWfoo2"])
    expected = [[u"CSWbar"]]
    result = m._MissingDepsFromReasonGroups(
        "CSWfoo", reason_groups, declared_deps)
    self.assertEqual(expected, result)

  def testMissingDepsFromReasonGroupsTwo(self):
    m = checkpkg_lib.CheckpkgManager2(
            "testname", [], "5.9", "sparc", "unstable")
    reason_groups = [
        [(u"CSWfoo1", "reason 1"),
         (u"CSWfoo2", "reason 1")],
        [(u"CSWbar", "reason 2")],
    ]
    declared_deps = set([])
    expected = [[u'CSWfoo1', u'CSWfoo2'], [u'CSWbar']]
    result = m._MissingDepsFromReasonGroups(
        "CSWfoo", reason_groups, declared_deps)
    self.assertEqual(result, expected)

  def testMissingDepsFromReasonGroupsSelf(self):
    m = checkpkg_lib.CheckpkgManager2(
            "testname", [], "5.9", "sparc", "unstable")
    reason_groups = [
        [(u"CSWfoo", "reason 1"),
         (u"CSWfoo2", "reason 1")],
    ]
    declared_deps = set([])
    expected = []
    result = m._MissingDepsFromReasonGroups(
        "CSWfoo", reason_groups, declared_deps)
    self.assertEqual(result, expected)

  def test_RemovePkgsFromMissing(self):
    m = checkpkg_lib.CheckpkgManager2(
            "testname", [], "5.9", "sparc", "unstable")
    missing_dep_groups = [['CSWfoo-one', 'CSWfoo']]
    expected = set(
        [
          frozenset(['CSWfoo', 'CSWfoo-one']),
        ]
    )
    result = m._RemovePkgsFromMissing("CSWbaz", missing_dep_groups)
    self.assertEqual(expected, result)

  def testReportMissingDependenciesOne(self):
    m = checkpkg_lib.CheckpkgManager2(
            "testname", [], "5.9", "sparc", "unstable")
    error_mgr_mock = self.mox.CreateMock(checkpkg_lib.IndividualCheckInterface)
    declared_deps = frozenset([u"CSWfoo"])
    req_pkgs_reasons = [
        [
          (u"CSWfoo", "reason 1"),
          (u"CSWfoo-2", "reason 2"),
        ],
        [
          ("CSWbar", "reason 3"),
        ],
    ]
    error_mgr_mock.ReportErrorForPkgname(
        'CSWexamined', 'missing-dependency', 'CSWbar')
    self.mox.ReplayAll()
    m._ReportMissingDependencies(
        error_mgr_mock, "CSWexamined", declared_deps, req_pkgs_reasons)

  def testReportMissingDependenciesTwo(self):
    m = checkpkg_lib.CheckpkgManager2(
            "testname", [], "5.9", "sparc", "unstable")
    error_mgr_mock = self.mox.CreateMock(checkpkg_lib.IndividualCheckInterface)
    declared_deps = frozenset([])
    req_pkgs_reasons = [
        [
          (u"CSWfoo-1", "reason 1"),
          (u"CSWfoo-2", "reason 1"),
        ],
    ]
    error_mgr_mock.ReportErrorForPkgname(
        'CSWexamined', 'missing-dependency', u'CSWfoo-1 or CSWfoo-2')
    self.mox.ReplayAll()
    m._ReportMissingDependencies(
        error_mgr_mock, "CSWexamined", declared_deps, req_pkgs_reasons)

  def DisabledtestReportMissingDependenciesIntegration(self):
    m = checkpkg_lib.CheckpkgManager2(
            "testname", [], "5.9", "sparc", "unstable")
    catalog_mock = self.mox.CreateMock(checkpkg_lib.Catalog)
    checkpkg_interface = checkpkg_lib.IndividualCheckInterface(
          "CSWfoo", "AlienOS5.2", "sparkle", "calcified", catalog_mock)
    declared_deps_by_pkgname = {
        "CSWfoo": frozenset(),
    }
    declared_deps = frozenset([])
    pkgs_providing_path = ["CSWproviding-%02d" % x for x in range(20)]
    catalog_mock.GetPkgByPath(
        '/opt/csw/sbin',
        'AlienOS5.2',
        'sparkle',
        'calcified').AndReturn(pkgs_providing_path)
    self.mox.ReplayAll()
    checkpkg_interface.NeedFile("/opt/csw/sbin", "reason 1")
    needed_files = checkpkg_interface.needed_files
    needed_pkgs = checkpkg_interface.needed_pkgs
    messenger_stub = stubs.MessengerStub()
    m._ReportDependencies(
        checkpkg_interface,
        needed_files,
        needed_pkgs,
        messenger_stub,
        declared_deps_by_pkgname)
    self.assertEqual(1, len(checkpkg_interface.errors))
    self.assertEqual(
        " or ".join(sorted(pkgs_providing_path)),
        checkpkg_interface.errors[0].tag_info)

  def testReportMissingDependenciesSurplus(self):
    m = checkpkg_lib.CheckpkgManager2(
            "testname", [], "5.9", "sparc", "unstable")
    error_mgr_mock = self.mox.CreateMock(checkpkg_lib.IndividualCheckInterface)
    declared_deps = frozenset([u"CSWfoo", u"CSWbar", u"CSWsurplus"])
    req_pkgs_reasons = [
        [
          (u"CSWfoo", "reason 1"),
          (u"CSWfoo-2", "reason 2"),
        ],
        [
          ("CSWbar", "reason 3"),
        ],
    ]
    error_mgr_mock.ReportErrorForPkgname(
        'CSWexamined', 'surplus-dependency', u'CSWsurplus')
    self.mox.ReplayAll()
    m._ReportMissingDependencies(
        error_mgr_mock, "CSWexamined", declared_deps, req_pkgs_reasons)


class CheckpkgManager2DatabaseIntegrationTest(
    test_base.SqlObjectTestMixin, mox.MoxTestBase):

  def SetUpStatsForTesting(self, pkgstat_module):
    for md5_sum, data in pkgstat_module.pkgstats[0]['elfdump_info'].iteritems():
      json = cjson.encode(data)
      content_hash = hashlib.md5()
      content_hash.update(json)
      models.ElfdumpInfoBlob(
          md5_sum=md5_sum,
          json=json,
          content_md5_sum=content_hash.hexdigest(),
          mime_type='application/json')
    data = copy.deepcopy(pkgstat_module.pkgstats[0])
    data['elf_callback'] = None
    json = cjson.encode(data)
    content_hash = hashlib.md5()
    content_hash.update(json)
    md5_sum = pkgstat_module.pkgstats[0]['basic_stats']['md5_sum']
    models.Srv4FileStatsBlob(
        md5_sum=md5_sum,
        json=json,
        content_md5_sum=content_hash.hexdigest(),
        mime_type='application/json')

    sqo_pkgstats, pkgstats = relational_util.StatsStructToDatabaseLevelOne(
        md5_sum, False)
    return sqo_pkgstats, pkgstats

  def SetUpMockCalls(self, pkgstats_module, pkg_md5_sum, pkgstats):
    # This is a stupid way of doing this. We would be better off with a fake.
    pkgstats_pruned = copy.copy(pkgstats)
    del pkgstats_pruned['elfdump_info']
    md5_by_binary = {}
    for bin_path, md5_sum in pkgstats['binary_md5_sums']:
      md5_by_binary[bin_path] = md5_sum
    self.rest_client_mock.GetBlob('pkgstats', pkg_md5_sum).AndReturn(
            pkgstats_pruned)
    for bin_path, _, _, sonames, _, _, _, _ in pkgstats['binaries_dump_info']:
      for soname in sorted(sonames):
        # self.rest_client_mock.GetBlob('elfinfo', md5_by_binary[bin_path])
        self.rest_client_mock.GetPathsAndPkgnamesByBasename(
            'unstable', 'sparc', 'SunOS5.9', soname).AndReturn({})
      # for soname in sorted(sonames):
      #   self.rest_client_mock.GetBlob('elfinfo', md5_by_binary[bin_path]).AndReturn(
      #       pkgstats['elfdump_info'][md5_sum])
    for binary_path, md5_sum in pkgstats['binary_md5_sums']:
      data = pkgstats['elfdump_info'][md5_sum]
      self.rest_client_mock.GetBlob(
          'elfdump', md5_sum).AndReturn(data)

  def setUp(self):
    super(CheckpkgManager2DatabaseIntegrationTest, self).setUp()
    self.rest_client_mock = self.mox.CreateMock(rest.RestClient)
    self.mox.StubOutWithMock(rest, 'RestClient')
    rest.RestClient(
        pkgdb_url=mox.IsA(str),
        releases_url=mox.IsA(str)).AndReturn(
            self.rest_client_mock)

  # Broken test
  # def testInsertNeon(self):
  #   self.dbc.InitialDataImport()
  #   sqo_pkg, pkgstats = self.SetUpStatsForTesting(neon_stats)
  #   # self.rest_client_mock.GetPathsAndPkgnamesByBasename(
  #   #     'unstable', 'sparc', 'SunOS5.9', 'libc.so.1').AndReturn({})
  #   # self.SetUpMockCalls(neon_stats, 'ba3b78331d2ed321900e5da71f7714c5', pkgstats)
  #   self.mox.ReplayAll()
  #   cm = checkpkg_lib.CheckpkgManager2(
  #       "testname", [sqo_pkg], "SunOS5.9", "sparc", "unstable",
  #       show_progress=False)
  #   cm.Run()
  #   # Verifying that there are some reported error tags.
  #   self.assertTrue(list(models.CheckpkgErrorTag.select()))

  # Broken test
  # def testReRunCheckpkg(self):
  #   """Error tags should not accumulate.

  #   FIXME(maciej): Figure out what's wrong with this one: It errors out.
  #   """
  #   self.dbc.InitialDataImport()
  #   sqo_pkg, pkgstats = self.SetUpStatsForTesting(neon_stats)
  #   self.SetUpMockCalls(neon_stats, 'ba3b78331d2ed321900e5da71f7714c5', pkgstats)
  #   self.SetUpMockCalls(neon_stats, 'ba3b78331d2ed321900e5da71f7714c5', pkgstats)
  #   self.mox.ReplayAll()
  #   cm = checkpkg_lib.CheckpkgManager2(
  #       "testname", [sqo_pkg], "SunOS5.9", "sparc", "unstable",
  #       show_progress=False)
  #   before_count = models.CheckpkgErrorTag.selectBy(srv4_file=sqo_pkg).count()
  #   cm.Run()
  #   first_run_count = models.CheckpkgErrorTag.selectBy(srv4_file=sqo_pkg).count()
  #   cm.Run()
  #   second_run_count = models.CheckpkgErrorTag.selectBy(srv4_file=sqo_pkg).count()
  #   self.assertEquals(0, before_count)
  #   self.assertEquals(first_run_count, second_run_count)


class IndividualCheckInterfaceUnitTest(mox.MoxTestBase):
  def setUp(self):
    super(IndividualCheckInterfaceUnitTest, self).setUp()
    self.rest_client_mock = self.mox.CreateMock(rest.RestClient)

  def testNeededFile(self):
    catalog_mock = self.mox.CreateMock(checkpkg_lib.Catalog)
    # Test that when you declare a file is needed, the right error
    # functions are called.
    self.mox.ReplayAll()
    ici = checkpkg_lib.IndividualCheckInterface(
        'CSWfoo', 'AlienOS5.1', 'amd65', 'calcified', catalog_mock, {}, None)
    ici.NeedFile("/opt/csw/bin/foo", "Because.")
    # This might look like encapsulation violation, but I think this is
    # a reasonable interface to that class.
    self.assertEqual(1, len(ici.needed_files))
    needed_file = ici.needed_files[0]
    self.assertEqual("CSWfoo", needed_file.pkgname)
    self.assertEqual("/opt/csw/bin/foo", needed_file.full_path)
    self.assertEqual("Because.", needed_file.reason)

  def testGetPkgByPathSelf(self):
    catalog_mock = self.mox.CreateMock(checkpkg_lib.Catalog)
    # Test that when you declare a file is needed, the right error
    # functions are called.
    pkg_set_files = {
        "CSWfoo": frozenset([
          ("/opt/csw", "bin"),
          ("/opt/csw/bin", "foo"),
        ]),
        "CSWbar": frozenset([
          ("/opt/csw/bin", "bar"),
        ]),
    }
    catalog_mock.GetPkgByPath(
        '/opt/csw/bin', 'AlienOS5.1', 'amd65', 'calcified').AndReturn(frozenset())
    self.mox.ReplayAll()
    ici = checkpkg_lib.IndividualCheckInterface(
        'CSWfoo', 'AlienOS5.1', 'amd65', 'calcified', catalog_mock, pkg_set_files, None)
    pkgs = ici.GetPkgByPath("/opt/csw/bin")
    self.assertEqual(frozenset(["CSWfoo"]), pkgs)

  def testGetPathsAndPkgnamesByBasename(self):
    catalog_mock = self.mox.CreateMock(checkpkg_lib.Catalog)
    # Test that when you declare a file is needed, the right error
    # functions are called.
    pkg_set_files = {
        "CSWfoo": frozenset([
          ("/opt/csw", "bin"),
          ("/opt/csw/bin", "foo"),
        ]),
        "CSWbar": frozenset([
          ("/opt/csw/bin", "bar"),
        ]),
    }
    in_catalog = {
        "/opt/csw/bin": ["CSWbar"],
        "/opt/csw/share/unrelated": ["CSWbaz"],
    }
    expected = {
        "/opt/csw/bin": ["CSWfoo"],
        "/opt/csw/share/unrelated": ["CSWbaz"],
    }
    self.rest_client_mock.GetPathsAndPkgnamesByBasename(
        'calcified', 'amd65', 'AlienOS5.1', 'foo').AndReturn(in_catalog)
    
    self.mox.ReplayAll()
    ici = checkpkg_lib.IndividualCheckInterface( 'CSWfoo', 'AlienOS5.1',
        'amd65', 'calcified', catalog_mock, pkg_set_files,
        self.rest_client_mock)
    paths_and_pkgnames = ici.GetPathsAndPkgnamesByBasename("foo")
    self.assertEqual(expected, paths_and_pkgnames)

  def testNeededPackage(self):
    catalog_mock = self.mox.CreateMock(checkpkg_lib.Catalog)
    # Test that when you declare a file is needed, the right error
    # functions are called.
    self.mox.ReplayAll()
    ici = checkpkg_lib.IndividualCheckInterface(
        'CSWfoo', 'AlienOS5.1', 'amd65', 'calcified', catalog_mock, {}, None)
    ici.NeedPackage("CSWbar", "Because foo needs bar")
    # This might look like encapsulation violation, but I think this is
    # a reasonable interface to that class.
    self.assertEqual(1, len(ici.needed_pkgs))
    needed_pkg = ici.needed_pkgs[0]
    self.assertEqual("CSWfoo", needed_pkg.pkgname)
    self.assertEqual("CSWbar", needed_pkg.needed_pkg)
    self.assertEqual("Because foo needs bar", needed_pkg.reason)


class SetCheckInterfaceUnitTest(mox.MoxTestBase):

  def testNeededFile(self):
    catalog_mock = self.mox.CreateMock(checkpkg_lib.Catalog)
    # Test that when you declare a file is needed, the right error
    # functions are called.
    self.mox.ReplayAll()
    sci = checkpkg_lib.SetCheckInterface(
        'AlienOS5.1', 'amd65', 'calcified', catalog_mock, {}, None)
    sci.NeedFile("CSWfoo", "/opt/csw/bin/foo", "Because.")
    # This might look like encapsulation violation, but I think this is
    # a reasonable interface to that class.
    self.assertEqual(1, len(sci.needed_files))
    needed_file = sci.needed_files[0]
    self.assertEqual("CSWfoo", needed_file.pkgname)
    self.assertEqual("/opt/csw/bin/foo", needed_file.full_path)
    self.assertEqual("Because.", needed_file.reason)


class ExtractorsUnitTest(unittest.TestCase):

  def testExtractDescriptionFromGoodData(self):
    data = {"NAME": "nspr_devel - Netscape Portable Runtime header files"}
    result = "Netscape Portable Runtime header files"
    self.assertEqual(result, checkpkg_lib.ExtractDescription(data))

  def testExtractDescriptionWithBadCatalogname(self):
    data = {"NAME": "foo-bar - Bad catalogname shouldn't break this function"}
    result = "Bad catalogname shouldn't break this function"
    self.assertEqual(result, checkpkg_lib.ExtractDescription(data))

  def testExtractMaintainerName(self):
    data = {"VENDOR": "https://ftp.mozilla.org/pub/mozilla.org/"
                      "nspr/releases/v4.8/src/ packaged for CSW by "
                      "Maciej Blizinski"}
    result = "Maciej Blizinski"
    self.assertEqual(result, checkpkg_lib.ExtractMaintainerName(data))

  def testPstampRegex(self):
    pstamp = "hson@solaris9s-csw-20100313144445"
    expected = {
        'username': 'hson',
        'timestamp': '20100313144445',
        'hostname': 'solaris9s-csw'
    }
    self.assertEqual(expected, re.match(common_constants.PSTAMP_RE, pstamp).groupdict())


class SliceListUnitTest(unittest.TestCase):

  def testOne(self):
    l = [1, 2, 3, 4, 5]
    s = 1
    expected = [[1], [2], [3], [4], [5]]
    self.assertTrue(expected, checkpkg_lib.SliceList(l, s))

  def testTwo(self):
    l = [1, 2, 3, 4, 5]
    s = 2
    expected = [[1, 2], [3, 4], [5]]
    self.assertTrue(expected, checkpkg_lib.SliceList(l, s))


class SqliteUnitTest(unittest.TestCase):

  """Makes sure that we can lose state between tests."""

  def setUp(self):
    self.conn = sqlite3.connect(":memory:")
    self.c = self.conn.cursor()

  def tearDown(self):
    self.conn = None

  def testCannotCreateTwoTables(self):
    self.c.execute("CREATE TABLE foo (INT bar);")
    self.assertRaises(
        sqlite3.OperationalError,
        self.c.execute, "CREATE TABLE foo (INT bar);")

  def testOne(self):
    self.c.execute("CREATE TABLE foo (INT bar);")

  def testTwo(self):
    self.c.execute("CREATE TABLE foo (INT bar);")

class SqlobjectUnitTest(test_base.SqlObjectTestMixin, unittest.TestCase):

  "Makes sure that we can lose state between methods."

  class TestModel(sqlobject.SQLObject):
    name = sqlobject.UnicodeCol(length=255, unique=True, notNone=True)

  # This does not work. Why?
  # def testCannotCreateTwoTables(self):
  #   self.TestModel.createTable()
  #   self.assertRaises(
  #       sqlite3.OperationalError,
  #       self.TestModel.createTable)

  def testOne(self):
    self.TestModel.createTable()

  def testTwo(self):
    self.TestModel.createTable()


if __name__ == '__main__':
  unittest.main()
