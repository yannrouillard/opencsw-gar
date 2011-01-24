#!/usr/bin/env python2.6

"""csw_upload_pkg.py - uploads packages to the database.

POST using pycurl code example taken from:
http://pycurl.cvs.sourceforge.net/pycurl/pycurl/tests/test_post2.py?view=markup
"""

from StringIO import StringIO
import pycurl
import logging
import optparse
import hashlib
import os.path
import opencsw
import json
import common_constants


BASE_URL = "http://buildfarm.opencsw.org/releases/"
USAGE = """%prog [ options ] <pkg1> [ <pkg2> [ ... ] ]

Uploads a set of packages to the unstable catalog in opencsw-future."""

class Error(Exception):
  pass


class RestCommunicationError(Error):
  pass


class PackageCheckError(Error):
  """A problem with the package."""


class Srv4Uploader(object):

  def __init__(self, filenames, debug=False):
    self.filenames = filenames
    self.md5_by_filename = {}
    self.debug = debug

  def Upload(self):
    for filename in self.filenames:
      parsed_basename = opencsw.ParsePackageFileName(
          os.path.basename(filename))
      if parsed_basename["vendortag"] != "CSW":
        raise PackageCheckError(
            "Package vendor tag is %s instead of CSW."
            % parsed_basename["vendortag"])
      self._UploadFile(filename)

  def Remove(self):
    for filename in self.filenames:
      self._RemoveFile(filename)

  def _RemoveFile(self, filename):
    md5_sum = self._GetFileMd5sum(filename)
    file_in_allpkgs, file_metadata = self._GetSrv4FileMetadata(md5_sum)
    osrel = file_metadata['osrel']
    arch = file_metadata['arch']
    self._IterateOverCatalogs(
        filename, file_metadata,
        arch, osrel, self._RemoveFromCatalog)

  def _RemoveFromCatalog(self, filename, arch, osrel, file_metadata):
    md5_sum = self._GetFileMd5sum(filename)
    basename = os.path.basename(filename)
    parsed_basename = opencsw.ParsePackageFileName(basename)
    url = (
        "%scatalogs/unstable/%s/%s/%s/"
        % (BASE_URL, arch, osrel, md5_sum))
    logging.debug("DELETE @ URL: %s %s", type(url), url)
    c = pycurl.Curl()
    d = StringIO()
    h = StringIO()
    c.setopt(pycurl.URL, str(url))
    c.setopt(pycurl.CUSTOMREQUEST, "DELETE")
    c.setopt(pycurl.WRITEFUNCTION, d.write)
    c.setopt(pycurl.HEADERFUNCTION, h.write)
    c.setopt(pycurl.HTTPHEADER, ["Expect:"]) # Fixes the HTTP 417 error
    if self.debug:
      c.setopt(c.VERBOSE, 1)
    c.perform()
    http_code = c.getinfo(pycurl.HTTP_CODE)
    logging.debug(
        "DELETE curl getinfo: %s %s %s",
        type(http_code),
        http_code,
        c.getinfo(pycurl.EFFECTIVE_URL))
    c.close()
    if http_code >= 400 and http_code <= 499:
      raise RestCommunicationError("%s - HTTP code: %s" % (url, http_code))

  def _GetFileMd5sum(self, filename):
    if filename not in self.md5_by_filename:
      logging.debug("_GetFileMd5sum(%s): Reading the file", filename)
      with open(filename, "rb") as fd:
        hash = hashlib.md5()
        hash.update(fd.read())
        md5_sum = hash.hexdigest()
        self.md5_by_filename[filename] = md5_sum
    return self.md5_by_filename[filename]

  def _IterateOverCatalogs(self, filename, file_metadata, arch, osrel, callback):
    # Implementing backward compatibility.  A package for SunOS5.x is also
    # inserted into SunOS5.(x+n) for n=(0, 1, ...)
    for idx, known_osrel in enumerate(common_constants.OS_RELS):
      if osrel == known_osrel:
        osrels = common_constants.OS_RELS[idx:]
    if arch == 'all':
      archs = ('sparc', 'i386')
    else:
      archs = (arch,)
    for arch in archs:
      for osrel in osrels:
        callback(filename, arch, osrel, file_metadata)

  def _UploadFile(self, filename):
    md5_sum = self._GetFileMd5sum(filename)
    file_in_allpkgs, file_metadata = self._GetSrv4FileMetadata(md5_sum)
    if file_in_allpkgs:
      logging.debug("File %s already uploaded.", filename)
    else:
      logging.debug("Uploading %s.", filename)
      self._PostFile(filename)
    file_in_allpkgs, file_metadata = self._GetSrv4FileMetadata(md5_sum)
    logging.debug("file_metadata %s", repr(file_metadata))
    osrel = file_metadata['osrel']
    arch = file_metadata['arch']
    self._IterateOverCatalogs(
        filename, file_metadata,
        arch, osrel, self._InsertIntoCatalog)

  def _InsertIntoCatalog(self, filename, arch, osrel, file_metadata):
    logging.info(
        "_InsertIntoCatalog(%s, %s, %s)",
        repr(arch), repr(osrel), repr(filename))
    md5_sum = self._GetFileMd5sum(filename)
    basename = os.path.basename(filename)
    parsed_basename = opencsw.ParsePackageFileName(basename)
    logging.debug("parsed_basename: %s", parsed_basename)
    url = (
        "%scatalogs/unstable/%s/%s/%s/"
        % (BASE_URL, arch, osrel, md5_sum))
    logging.debug("URL: %s %s", type(url), url)
    c = pycurl.Curl()
    d = StringIO()
    h = StringIO()
    # Bogus data to upload
    s = StringIO()
    c.setopt(pycurl.URL, str(url))
    c.setopt(pycurl.PUT, 1)
    c.setopt(pycurl.UPLOAD, 1)
    c.setopt(pycurl.INFILESIZE_LARGE, s.len)
    c.setopt(pycurl.READFUNCTION, s.read)
    c.setopt(pycurl.WRITEFUNCTION, d.write)
    c.setopt(pycurl.HEADERFUNCTION, h.write)
    c.setopt(pycurl.HTTPHEADER, ["Expect:"]) # Fixes the HTTP 417 error
    if self.debug:
      c.setopt(c.VERBOSE, 1)
    c.perform()
    http_code = c.getinfo(pycurl.HTTP_CODE)
    logging.debug(
        "curl getinfo: %s %s %s",
        type(http_code),
        http_code,
        c.getinfo(pycurl.EFFECTIVE_URL))
    c.close()
    # if self.debug:
    #   logging.debug("*** Headers")
    #   logging.debug(h.getvalue())
    #   logging.debug("*** Data")
    if http_code >= 400 and http_code <= 499:
      if not self.debug:
        # In debug mode, all headers are printed to screen, and we aren't
        # interested in the response body.
        logging.fatal("Response: %s %s", http_code, d.getvalue())
      raise RestCommunicationError("%s - HTTP code: %s" % (url, http_code))
    else:
      logging.info("Response: %s %s", http_code, d.getvalue())
    return http_code

  def _GetSrv4FileMetadata(self, md5_sum):
    logging.debug("_GetSrv4FileMetadata(%s)", repr(md5_sum))
    url = BASE_URL + "srv4/" + md5_sum + "/"
    c = pycurl.Curl()
    d = StringIO()
    h = StringIO()
    c.setopt(pycurl.URL, url)
    c.setopt(pycurl.WRITEFUNCTION, d.write)
    c.setopt(pycurl.HEADERFUNCTION, h.write)
    if self.debug:
      c.setopt(c.VERBOSE, 1)
    c.perform()
    http_code = c.getinfo(pycurl.HTTP_CODE)
    logging.debug(
        "curl getinfo: %s %s %s",
        type(http_code),
        http_code,
        c.getinfo(pycurl.EFFECTIVE_URL))
    c.close()
    if self.debug:
      logging.debug("*** Headers")
      logging.debug(h.getvalue())
      logging.debug("*** Data")
      logging.debug(d.getvalue())
    successful = http_code >= 200 and http_code <= 299
    metadata = None
    if successful:
      metadata = json.loads(d.getvalue())
    return successful, metadata

  def _PostFile(self, filename):
    logging.info("_PostFile(%s)", repr(filename))
    md5_sum = self._GetFileMd5sum(filename)
    c = pycurl.Curl()
    d = StringIO()
    h = StringIO()
    url = BASE_URL + "srv4/"
    c.setopt(pycurl.URL, url)
    c.setopt(pycurl.POST, 1)
    post_data = [
        ('srv4_file', (pycurl.FORM_FILE, filename)),
        ('submit', 'Upload'),
        ('md5_sum', md5_sum),
        ('basename', os.path.basename(filename)),
    ]
    c.setopt(pycurl.HTTPPOST, post_data)
    c.setopt(pycurl.WRITEFUNCTION, d.write)
    c.setopt(pycurl.HEADERFUNCTION, h.write)
    c.setopt(pycurl.HTTPHEADER, ["Expect:"]) # Fixes the HTTP 417 error
    if self.debug:
      c.setopt(c.VERBOSE, 1)
    c.perform()
    http_code = c.getinfo(pycurl.HTTP_CODE)
    c.close()
    if self.debug:
      logging.debug("*** Headers")
      logging.debug(h.getvalue())
      logging.debug("*** Data")
      logging.debug(d.getvalue())
    logging.debug("File POST http code: %s", http_code)
    if http_code >= 400 and http_code <= 499:
      raise RestCommunicationError("%s - HTTP code: %s" % (url, http_code))


if __name__ == '__main__':
  parser = optparse.OptionParser(USAGE)
  parser.add_option("-d", "--debug",
      dest="debug",
      default=False, action="store_true")
  parser.add_option("--remove",
      dest="remove",
      default=False, action="store_true")
  options, args = parser.parse_args()
  print "args:", args
  if options.debug:
    logging.basicConfig(level=logging.DEBUG)
  else:
    logging.basicConfig(level=logging.INFO)
  uploader = Srv4Uploader(args, debug=options.debug)
  if options.remove:
    uploader.Remove()
  else:
    uploader.Upload()
