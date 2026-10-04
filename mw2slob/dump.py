import contextlib
import json
import logging
import multiprocessing
import os
import re
import sqlite3
import tarfile
from array import array
from io import TextIOWrapper
from typing import IO
from typing import Iterable
from typing import Iterator
from typing import Optional
from typing import Sequence
from typing import Set
from typing import Tuple
from typing import Union

from . import convert
from . import siteinfo as si

log = logging.getLogger(__name__)


def replace_extensions(path: str, new_exts: Iterable = ()) -> str:
    """
    >>> replace_extensions("/a/b/c/dump.njson.tar.gz")
    '/a/b/c/dump'
    >>> replace_extensions("dump.njson.tar.gz")
    'dump'
    >>> replace_extensions("dump.njson.tar.gz", new_exts=["slob"])
    'dump.slob'
    >>> replace_extensions("/a/b/c/dump.njson.tar.gz", new_exts=["siteinfo", "json"])
    '/a/b/c/dump.siteinfo.json'
    """
    basename = os.path.basename(path)
    dirname = os.path.dirname(path)
    noext, *_ = basename.split(os.path.extsep)
    return os.path.join(dirname, os.path.extsep.join((noext, *new_exts)))


def get_outname(args):
    outname = args.output_file
    if outname is None:
        basename = os.path.basename(args.dump_file[0])
        outname = replace_extensions(basename, ["slob"])
    return outname


def get_siteinfo(args):
    siteinfo_path = args.siteinfo
    if not siteinfo_path:
        siteinfo_path = replace_extensions(args.dump_file, ["siteinfo", "json"])

    with open(siteinfo_path) as siteinfo_file:
        siteinfo_dict = json.load(siteinfo_file)

    return siteinfo_dict


def dump_members(dump_file: str) -> Iterator[Union[TextIOWrapper, IO[bytes]]]:
    """The newline-delimited JSON files of a dump: each member of a .tar or
    .tar.gz archive, or the dump file itself."""
    dump_file = os.path.expanduser(dump_file)
    if dump_file.endswith((".tar.gz", ".tar")):
        with tarfile.open(dump_file) as tar:
            for member in tar:
                f = tar.extractfile(member)
                if f is not None:
                    yield f
    else:
        with open(dump_file) as f:
            yield f


# A Wikimedia Enterprise snapshot can contain the same page several times, at
# successive revisions, and occasionally the same revision twice. The page
# index records, for every page in a set of dump files, its newest revision and
# how many records it has, so that the conversion pass can convert each page
# once, at that revision. It's built by a first pass over all the dump files -
# the newest copy can be in a later file than a stale one - and kept next to the
# dump as a SQLite file, so later conversions of the same dump reuse it.

PAGE_INDEX_SCHEMA = """
CREATE TABLE page (
    id INTEGER PRIMARY KEY,
    rev INTEGER NOT NULL,
    copies INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE source (
    name TEXT NOT NULL,
    size INTEGER NOT NULL
);
"""

# Keeps the newest revision whatever order a page's copies come in.
PAGE_INDEX_UPSERT = """
INSERT INTO page (id, rev) VALUES (?, ?)
ON CONFLICT (id) DO UPDATE SET rev = max(rev, excluded.rev), copies = copies + 1
"""


def default_page_index_path(dump_files: Sequence[str]) -> str:
    """
    >>> default_page_index_path(["/d/simplewiki_namespace_0_chunk_0.tar.gz",
    ...                          "/d/simplewiki_namespace_0_chunk_1.tar.gz"])
    '/d/simplewiki_namespace_0.pages.sqlite'
    >>> default_page_index_path(["/d/enwiki_namespace_0.tar.gz"])
    '/d/enwiki_namespace_0.pages.sqlite'
    """
    first = os.path.expanduser(dump_files[0])
    base = re.sub(r"_chunk_\d+$", "", replace_extensions(os.path.basename(first)))
    return os.path.join(os.path.dirname(first), f"{base}.pages.sqlite")


def _dump_sources(dump_files: Sequence[str]) -> Set[Tuple[str, int]]:
    return {
        (os.path.basename(f), os.path.getsize(os.path.expanduser(f)))
        for f in dump_files
    }


def _page_revisions(dump_file: str) -> Tuple[str, array, array]:
    """Page id and revision id of every record in a dump file (run in a worker
    process; flat arrays keep the result compact to hold and send back)."""
    page_ids, revisions = array("q"), array("q")
    for f in dump_members(dump_file):
        for line in f:
            try:
                data = json.loads(line)
                page_id = data["identifier"]
                revision = data["version"]["identifier"]
            except Exception:
                # Left out of the index; the conversion pass converts such a
                # record as is (counting it as not in the index), or reports it
                # if it can't be read at all.
                continue
            page_ids.append(page_id)
            revisions.append(revision)
    return dump_file, page_ids, revisions


def build_page_index(dump_files: Sequence[str], path: str) -> None:
    """Make sure the page index at `path` covers `dump_files`.

    An existing index is reused if it was built from (at least) these dump
    files, matched by name and size; otherwise it's rebuilt from them. The index
    is written under a temporary name and renamed when complete, so an
    interrupted build is never mistaken for a finished one.
    """
    sources = _dump_sources(dump_files)
    if os.path.exists(path):
        try:
            with contextlib.closing(sqlite3.connect(path)) as cx:
                indexed = set(cx.execute("SELECT name, size FROM source"))
        except sqlite3.Error as ex:
            print(f"Page index {path} is unreadable ({ex}), rebuilding")
        else:
            if sources <= indexed:
                print(f"Using page index {path}")
                return
            print(f"Page index {path} was built from other dump files, rebuilding")

    print(f"Building page index {path}")
    tmp = f"{path}.tmp"
    if os.path.exists(tmp):
        os.remove(tmp)
    records = 0
    with contextlib.closing(sqlite3.connect(tmp)) as cx:
        cx.executescript(PAGE_INDEX_SCHEMA)
        cx.executemany("INSERT INTO source (name, size) VALUES (?, ?)", sorted(sources))
        with multiprocessing.Pool() as pool:
            for dump_file, page_ids, revisions in pool.imap_unordered(
                _page_revisions, dump_files
            ):
                cx.executemany(PAGE_INDEX_UPSERT, zip(page_ids, revisions))
                records += len(page_ids)
                print(f"  {dump_file}: {len(page_ids)} records")
        cx.commit()
        (pages,) = cx.execute("SELECT count(*) FROM page").fetchone()
        (repeated,) = cx.execute("SELECT count(*) FROM page WHERE copies > 1").fetchone()
    os.replace(tmp, path)
    print(
        f"Page index: {records} records of {pages} pages, "
        f"{repeated} pages with more than one record"
    )


class PageIndex:
    """Decides, during the conversion pass, which records to convert: a page's
    newest revision, once."""

    def __init__(self, path: str):
        self._cx = sqlite3.connect(path)
        # Pages with several records whose newest revision was already
        # converted, so a repeat of that same revision is skipped too.
        self._converted: Set[int] = set()
        self.superseded = 0
        self.repeated = 0
        self.unindexed = 0

    def is_current(self, page_id: Optional[int], revision: Optional[int]) -> bool:
        row = self._cx.execute(
            "SELECT rev, copies FROM page WHERE id = ?", (page_id,)
        ).fetchone()
        if row is None or revision is None:
            self.unindexed += 1
            return True
        newest, copies = row
        if revision != newest:
            self.superseded += 1
            return False
        if copies > 1:
            if page_id in self._converted:
                self.repeated += 1
                return False
            self._converted.add(page_id)
        return True

    def close(self) -> None:
        self._cx.close()


def parse_loc_spec(s: str) -> Tuple[int, int]:
    if ":" in s:
        fileno, lineno = s.split(":")
        return int(fileno), int(lineno)
    return 1, int(s)


def articles(
    dump_files: Sequence[str],
    info: si.Info,
    start_line_spec: str = "1:1",
    end_line_spec: Optional[str] = None,
    html_encoding="utf-8",
    remove_embedded_bg="",
    ensure_ext_image_urls=True,
    page_index_path: Optional[str] = None,
) -> Iterable[convert.ConvertParams]:

    start_file, start_line = parse_loc_spec(start_line_spec)
    if end_line_spec:
        end_file, end_line = parse_loc_spec(end_line_spec)
    else:
        end_file, end_line = None, None

    # Opened here rather than passed in open: the conversion pool pulls from
    # this generator on its own thread, and a SQLite connection must be used on
    # the thread that opened it.
    page_index = PageIndex(page_index_path) if page_index_path else None

    for dump_file in dump_files:
        print(f"Reading articles from ${dump_file}")
        members = dump_members(dump_file)
        with contextlib.closing(members):
            for k, f in enumerate(members):
                file_number = k + 1
                if file_number < start_file:
                    continue
                if end_file and file_number > end_file:
                    break
                for i, line in enumerate(f):
                    line_number = i + 1
                    j = 0
                    if line_number < start_line:
                        if i % 1000 == 0:
                            print(".", end="", flush=True)
                            j += 1
                        if j % 50 == 0:
                            print(flush=True)
                            j = 0
                        continue
                    if end_line and line_number > end_line:
                        break
                    try:
                        data = json.loads(line)
                        html = data["article_body"]["html"]
                        title = data["name"]
                        if page_index and not page_index.is_current(
                            data.get("identifier"),
                            (data.get("version") or {}).get("identifier"),
                        ):
                            print(f"{file_number}:{line_number} {title} (skipped)")
                            continue
                        redirects = data.get("redirects", ())
                        aliases = [r["name"] for r in redirects]
                        print(f"{file_number}:{line_number} {title} ({len(html)})")
                        yield convert.ConvertParams(
                            title=title,
                            aliases=aliases,
                            text=html,
                            rtl=info.rtl,
                            server=info.server,
                            articlepath="./",  # TODO needs to be arg?
                            site_articlepath=info.articlepath,
                            encoding=html_encoding,
                            remove_embedded_bg=remove_embedded_bg,
                            ensure_ext_image_urls=ensure_ext_image_urls,
                        )
                    except:
                        log.exception(f"Failed to read line {i}")

    if page_index:
        page_index.close()
        print(
            f"Skipped {page_index.superseded} superseded and "
            f"{page_index.repeated} repeated page records; "
            f"{page_index.unindexed} records weren't in the page index"
        )
