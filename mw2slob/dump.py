import json
import logging
import os
import tarfile
from io import TextIOWrapper
from typing import IO
from typing import Iterable
from typing import Optional
from typing import Sequence
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
) -> Iterable[convert.ConvertParams]:

    start_file, start_line = parse_loc_spec(start_line_spec)
    if end_line_spec:
        end_file, end_line = parse_loc_spec(end_line_spec)
    else:
        end_file, end_line = None, None

    for dump_file in dump_files:
        dump_file = os.path.expanduser(dump_file)
        print(f"Reading articles from ${dump_file}")
        files: Iterable[Union[TextIOWrapper, IO[bytes]]] = []

        if dump_file.endswith(".tar.gz") or dump_file.endswith(".tar"):
            if dump_file.endswith(".tar.gz"):
                tar = tarfile.open(dump_file, "r:gz")
            else:
                tar = tarfile.open(dump_file, "r")
            ctx_manager = tar
            files = (
                f for f in (tar.extractfile(member) for member in tar) if f is not None
            )
        else:
            ctx_manager = open(dump_file)
            files = [ctx_manager]

        with ctx_manager:
            for k, f in enumerate(files):
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
