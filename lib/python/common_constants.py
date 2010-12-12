ARCH_SPARC = "sparc"
ARCH_i386 = "i386"
ARCH_ALL = "all"
PHYSICAL_ARCHITECTURES = [ARCH_SPARC, ARCH_i386]
ARCHITECTURES = PHYSICAL_ARCHITECTURES + [ARCH_ALL]
OS_RELS = [
    u"SunOS5.8",
    u"SunOS5.9",
    u"SunOS5.10",
    u"SunOS5.11",
]

SYSTEM_SYMLINKS = (
    ("/opt/csw/bdb4",     ["/opt/csw/bdb42"]),
    ("/64",               ["/amd64", "/sparcv9"]),
    ("/opt/csw/lib/i386", ["/opt/csw/lib"]),
)

DEFAULT_INSTALL_CONTENTS_FILE = "/var/sadm/install/contents"

OWN_PKGNAME_PREFIXES = frozenset(["CSW"])

# TODO: Merge with sharedlib_utils
# Based on 'isalist' output.  These are hardcoded here, so that it's possible to
# index a sparc package on a i386 machine and vice versa.
ISALISTS_BY_ARCH = {
    ARCH_SPARC: frozenset([
        "sparcv9+vis2",
        "sparcv9+vis",
        "sparcv9",
        "sparcv8plus+vis2",
        "sparcv8plus+vis",
        "sparcv8plus",
        "sparcv8",
        "sparcv8-fsmuld",
        "sparcv7",
        "sparc",
        ]),
    ARCH_i386: frozenset([
        "amd64",
        "pentium_pro+mmx",
        "pentium_pro",
        "pentium+mmx",
        "pentium",
        "i486",
        "i386",
        "i86",
    ]),
    ARCH_ALL: frozenset([]),
}

DEFAULT_CATALOG_RELEASES = frozenset([
    'current',
    'experimenta',
    'unstable',
    'testing',
    'stable',
    ])
