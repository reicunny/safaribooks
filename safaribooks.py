#!/usr/bin/env python3
# coding: utf-8
import re
import os
import sys
import json
import shutil
import pathlib
import getpass
import logging
import argparse
import requests
import traceback
from html import escape
from random import random
from lxml import html, etree
from multiprocessing import Process, Queue, Value
from urllib.parse import urljoin, urlparse, parse_qs, quote_plus


if getattr(sys, "frozen", False):
    # PyInstaller one-file: __file__ points into the temp _MEI* dir,
    # so resolve writable files (cookies.json, Books/, logs) next to the exe.
    PATH = os.path.dirname(sys.executable)
else:
    PATH = os.path.dirname(os.path.realpath(__file__))
COOKIES_FILE = os.path.join(PATH, "cookies.json")

ORLY_BASE_HOST = "oreilly.com"  # PLEASE INSERT URL HERE

SAFARI_BASE_HOST = "learning." + ORLY_BASE_HOST
API_ORIGIN_HOST = "api." + ORLY_BASE_HOST

ORLY_BASE_URL = "https://www." + ORLY_BASE_HOST
SAFARI_BASE_URL = "https://" + SAFARI_BASE_HOST
API_ORIGIN_URL = "https://" + API_ORIGIN_HOST
PROFILE_URL = SAFARI_BASE_URL + "/profile/"

# DEBUG
USE_PROXY = False
PROXIES = {"https": "https://127.0.0.1:8080"}


class Display:
    BASE_FORMAT = logging.Formatter(
        fmt="[%(asctime)s] %(message)s",
        datefmt="%d/%b/%Y %H:%M:%S"
    )

    SH_DEFAULT = "\033[0m" if "win" not in sys.platform else ""  # TODO: colors for Windows
    SH_YELLOW = "\033[33m" if "win" not in sys.platform else ""
    SH_BG_RED = "\033[41m" if "win" not in sys.platform else ""
    SH_BG_YELLOW = "\033[43m" if "win" not in sys.platform else ""

    def __init__(self, log_file):
        self.output_dir = ""
        self.output_dir_set = False
        self.log_file = os.path.join(PATH, log_file)

        self.logger = logging.getLogger("SafariBooks")
        self.logger.setLevel(logging.INFO)
        logs_handler = logging.FileHandler(filename=self.log_file, encoding="utf-8")
        logs_handler.setFormatter(self.BASE_FORMAT)
        logs_handler.setLevel(logging.INFO)
        self.logger.addHandler(logs_handler)

        self.columns, _ = shutil.get_terminal_size()

        self.logger.info("** Welcome to SafariBooks! **")

        self.book_ad_info = False
        self.css_ad_info = Value("i", 0)
        self.images_ad_info = Value("i", 0)
        self.last_request = (None,)
        self.in_error = False

        self.state_status = Value("i", 0)
        sys.excepthook = self.unhandled_exception

    def set_output_dir(self, output_dir):
        self.info("Output directory:\n    %s" % output_dir)
        self.output_dir = output_dir
        self.output_dir_set = True

    def unregister(self):
        self.logger.handlers[0].close()
        sys.excepthook = sys.__excepthook__

    def log(self, message):
        if isinstance(message, bytes):
            try:
                message = message.decode("utf-8", "replace")
            except Exception:
                message = repr(message)
        else:
            try:
                message = str(message)
            except Exception:
                message = repr(message)
        try:
            self.logger.info(message)
        except Exception:
            try:
                self.logger.info(message.encode("ascii", "replace").decode("ascii"))
            except Exception:
                pass

    def out(self, put):
        pattern = "\r{!s}\r{!s}\n"
        if isinstance(put, bytes):
            try:
                put = put.decode("utf-8", "replace")
            except Exception:
                put = repr(put)
        s = pattern.format(" " * self.columns, put)

        try:
            sys.stdout.write(s)
        except UnicodeEncodeError:
            # Windows consoles (cp1252/cp850) can't encode chars like 'ł' (U+0142).
            # Fall back to replacement chars instead of crashing the download.
            encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
            try:
                sys.stdout.write(s.encode(encoding, "replace").decode(encoding))
            except Exception:
                sys.stdout.write(s.encode("ascii", "replace").decode("ascii"))

    def info(self, message, state=False):
        self.log(message)
        output = (self.SH_YELLOW + "[*]" + self.SH_DEFAULT if not state else
                  self.SH_BG_YELLOW + "[-]" + self.SH_DEFAULT) + " %s" % message
        self.out(output)

    def error(self, error):
        if not self.in_error:
            self.in_error = True

        self.log(error)
        output = self.SH_BG_RED + "[#]" + self.SH_DEFAULT + " %s" % error
        self.out(output)

    def exit(self, error):
        self.error(str(error))

        if self.output_dir_set:
            output = (self.SH_YELLOW + "[+]" + self.SH_DEFAULT +
                      " Please delete the output directory '" + self.output_dir + "'"
                      " and restart the program.")
            self.out(output)

        output = self.SH_BG_RED + "[!]" + self.SH_DEFAULT + " Aborting..."
        self.out(output)

        self.save_last_request()
        sys.exit(1)

    def unhandled_exception(self, _, o, tb):
        self.log("".join(traceback.format_tb(tb)))
        self.exit("Unhandled Exception: %s (type: %s)" % (o, o.__class__.__name__))

    def save_last_request(self):
        if any(self.last_request):
            self.log("Last request done:\n\tURL: {0}\n\tDATA: {1}\n\tOTHERS: {2}\n\n\t{3}\n{4}\n\n{5}\n"
                     .format(*self.last_request))

    def intro(self):
        output = self.SH_YELLOW + (r"""
       ____     ___         _
      / __/__ _/ _/__ _____(_)
     _\ \/ _ `/ _/ _ `/ __/ /
    /___/\_,_/_/ \_,_/_/ /_/
      / _ )___  ___  / /__ ___
     / _  / _ \/ _ \/  '_/(_-<
    /____/\___/\___/_/\_\/___/
""" if random() > 0.5 else r"""
 ██████╗     ██████╗ ██╗  ██╗   ██╗██████╗
██╔═══██╗    ██╔══██╗██║  ╚██╗ ██╔╝╚════██╗
██║   ██║    ██████╔╝██║   ╚████╔╝   ▄███╔╝
██║   ██║    ██╔══██╗██║    ╚██╔╝    ▀▀══╝
╚██████╔╝    ██║  ██║███████╗██║     ██╗
 ╚═════╝     ╚═╝  ╚═╝╚══════╝╚═╝     ╚═╝
""") + self.SH_DEFAULT
        output += "\n" + "~" * (self.columns // 2)

        self.out(output)

    def parse_description(self, desc):
        if not desc:
            return "n/d"

        try:
            return html.fromstring(desc).text_content()

        except (html.etree.ParseError, html.etree.ParserError) as e:
            self.log("Error parsing the description: %s" % e)
            return "n/d"

    def book_info(self, info):
        description = self.parse_description(info.get("description", None)).replace("\n", " ")
        for t in [
            ("Title", info.get("title", "")), ("Authors", ", ".join(aut.get("name", "") for aut in info.get("authors", []))),
            ("Identifier", info.get("identifier", "")), ("ISBN", info.get("isbn", "")),
            ("Publishers", ", ".join(pub.get("name", "") for pub in info.get("publishers", []))),
            ("Rights", info.get("rights", "")),
            ("Description", description[:500] + "..." if len(description) >= 500 else description),
            ("Release Date", info.get("issued", "")),
            ("URL", info.get("web_url", ""))
        ]:
            self.info("{0}{1}{2}: {3}".format(self.SH_YELLOW, t[0], self.SH_DEFAULT, t[1]), True)

    def state(self, origin, done):
        progress = int(done * 100 / origin)
        bar = int(progress * (self.columns - 11) / 100)
        if self.state_status.value < progress:
            self.state_status.value = progress
            sys.stdout.write(
                "\r    " + self.SH_BG_YELLOW + "[" + ("#" * bar).ljust(self.columns - 11, "-") + "]" +
                self.SH_DEFAULT + ("%4s" % progress) + "%" + ("\n" if progress == 100 else "")
            )

    def done(self, epub_file):
        self.info("Done: %s\n\n" % epub_file +
                  "    If you like it, please * this project on GitHub to make it known:\n"
                  "        https://github.com/lorenzodifuccia/safaribooks\n"
                  "    e don't forget to renew your Safari Books Online subscription:\n"
                  "        " + SAFARI_BASE_URL + "\n\n" +
                  self.SH_BG_RED + "[!]" + self.SH_DEFAULT + " Bye!!")

    @staticmethod
    def api_error(response, cookies_file=COOKIES_FILE):
        message = "API: "
        detail = ""
        if isinstance(response, dict):
            detail = str(response.get("detail", "") or response.get("message", ""))
        elif isinstance(response, str):
            detail = response
        # v1: "Not found..."; v2: "No EpubArchive matches the given query.",
        # "{ "message": "Not Found" }".
        if detail and any(s in detail for s in ("Not found", "Not Found", "No EpubArchive")):
            message += "book's not present in Safari Books Online.\n" \
                       "    The book identifier is the digits that you can find in the URL:\n" \
                       "    `" + SAFARI_BASE_URL + "/library/view/book-name/XXXXXXXXXXXXX/`"

        else:
            if os.path.isfile(cookies_file):
                try:
                    os.remove(cookies_file)
                except OSError:
                    pass
            suffix = ""
            if isinstance(response, dict):
                raw = response.get("detail", "") or response.get("message", "")
                if raw:
                    suffix = " (%s)" % raw
            elif isinstance(response, str) and response.strip():
                suffix = " (%s)" % response.strip()[:200]
            message += "Out-of-Session%s.\n" % suffix + \
                       Display.SH_YELLOW + "[+]" + Display.SH_DEFAULT + \
                       " Use the `--cred` or `--login` options in order to perform the auth login to Safari."

        return message


class WinQueue(list):  # TODO: error while use `process` in Windows: can't pickle _thread.RLock objects
    def put(self, el):
        self.append(el)

    def qsize(self):
        return self.__len__()


def load_cookies_file(path):
    """Load cookies.json in console or script format.

    Accepted:
      - dict: {"orm-jwt": "...", "orm-rt": "...", ...} (console snippet and
        retrieve_cookies.py both produce this)
      - list: [{"name": "...", "value": "..."}, ...] (common cookie exporters)

    Returns a plain {name: value} dict. Raises ValueError with an actionable
    message instead of a raw JSONDecodeError.
    """
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            raw = f.read()
    except OSError as exc:
        raise ValueError("unable to read `%s`: %s" % (path, exc))

    if not raw.strip():
        raise ValueError("`%s` is empty" % path)

    text = raw.strip()
    # Tolerate a doubly-stringified file, e.g. file literally contains
    # '"{...}"' because the console output was pasted with outer quotes.
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"' and "orm-jwt" in text:
        try:
            text = json.loads(text)
        except ValueError:
            pass

    try:
        data = json.loads(text)
    except ValueError as exc:
        raise ValueError(
            "invalid JSON in `%s`: %s\n"
            "    This usually means the console output was truncated while copying\n"
            "    (e.g. `Unterminated string ... char 3144` means the file ends mid-value).\n"
            "    Re-copy the full console output (use right-click > Copy, not manual\n"
            "    selection), or use the Blob-download snippet from issue #358, or run\n"
            "    `python3 retrieve_cookies.py` instead. Validate with:\n"
            "        python3 -m json.tool cookies.json" % (path, exc)
        )

    if isinstance(data, dict):
        cookies = data
    elif isinstance(data, list):
        cookies = {}
        for entry in data:
            if isinstance(entry, dict) and "name" in entry:
                cookies[str(entry["name"])] = str(entry.get("value", ""))
            else:
                raise ValueError(
                    "unsupported list entry in `%s`: %r\n"
                    "    Expected [{\"name\": ..., \"value\": ...}, ...] or {\"name\": value}."
                    % (path, entry)
                )
    else:
        raise ValueError(
            "unsupported format in `%s`: expected a JSON object or a name/value list."
            % path
        )

    # Normalize values to strings; drop empty names.
    normalized = {}
    for name, value in cookies.items():
        if not name:
            continue
        normalized[str(name)] = value if isinstance(value, str) else str(value)

    if not normalized:
        raise ValueError("no usable cookies found in `%s`" % path)

    return normalized


class SafariBooks:
    LOGIN_URL = ORLY_BASE_URL + "/member/auth/login/"
    LOGIN_ENTRY_URL = SAFARI_BASE_URL + "/login/unified/?next=/home/"

    API_TEMPLATE = SAFARI_BASE_URL + "/api/v1/book/{0}/"

    # v2 API (current). Old v1 /api/v1/book/{id}/ now returns 404.
    EPUB_URL_TEMPLATE = SAFARI_BASE_URL + "/api/v2/epubs/urn:orm:book:{0}/"
    EPUB_FILES_TEMPLATE = SAFARI_BASE_URL + "/api/v2/epubs/urn:orm:book:{0}/files/"
    EPUB_SPINE_TEMPLATE = SAFARI_BASE_URL + "/api/v2/epubs/urn:orm:book:{0}/spine/"
    EPUB_TOC_TEMPLATE = SAFARI_BASE_URL + "/api/v2/epubs/urn:orm:book:{0}/table-of-contents/"
    EPUB_CHAPTERS_TEMPLATE = SAFARI_BASE_URL + "/api/v2/epub-chapters/?epub_identifier=urn:orm:book:{0}"
    METADATA_TEMPLATE = SAFARI_BASE_URL + "/api/v2/metadata/?ourn=urn%3Aorm%3Abook%3A{0}&limit=1"
    TALENT_TEMPLATE = SAFARI_BASE_URL + "/api/v1/talent/work/urn:orm:book:{0}"

    BASE_01_HTML = "<!DOCTYPE html>\n" \
                   "<html lang=\"en\" xml:lang=\"en\" xmlns=\"http://www.w3.org/1999/xhtml\"" \
                   " xmlns:xsi=\"http://www.w3.org/2001/XMLSchema-instance\"" \
                   " xsi:schemaLocation=\"http://www.w3.org/2002/06/xhtml2/" \
                   " http://www.w3.org/MarkUp/SCHEMA/xhtml2.xsd\"" \
                   " xmlns:epub=\"http://www.idpf.org/2007/ops\">\n" \
                   "<head>\n" \
                   "{0}\n" \
                   "<style type=\"text/css\">" \
                   "body{{margin:1em;background-color:transparent!important;}}" \
                   "#sbo-rt-content *{{text-indent:0pt!important;}}#sbo-rt-content .bq{{margin-right:1em!important;}}"

    KINDLE_HTML = "#sbo-rt-content *{{word-wrap:break-word!important;" \
                  "word-break:break-word!important;}}#sbo-rt-content table,#sbo-rt-content pre" \
                  "{{overflow-x:unset!important;overflow:unset!important;" \
                  "overflow-y:unset!important;white-space:pre-wrap!important;}}"

    BASE_02_HTML = "</style>" \
                   "</head>\n" \
                   "<body>{1}</body>\n</html>"

    CONTAINER_XML = "<?xml version=\"1.0\"?>" \
                    "<container version=\"1.0\" xmlns=\"urn:oasis:names:tc:opendocument:xmlns:container\">" \
                    "<rootfiles>" \
                    "<rootfile full-path=\"OEBPS/content.opf\" media-type=\"application/oebps-package+xml\" />" \
                    "</rootfiles>" \
                    "</container>"

    # Format: ID, Title, Authors, Description, Subjects, Publisher, Rights, Date, CoverId, MANIFEST, SPINE, CoverUrl
    CONTENT_OPF = "<?xml version=\"1.0\" encoding=\"utf-8\"?>\n" \
                  "<package xmlns=\"http://www.idpf.org/2007/opf\" unique-identifier=\"bookid\" version=\"2.0\" >\n" \
                  "<metadata xmlns:dc=\"http://purl.org/dc/elements/1.1/\" " \
                  " xmlns:opf=\"http://www.idpf.org/2007/opf\">\n" \
                  "<dc:title>{1}</dc:title>\n" \
                  "{2}\n" \
                  "<dc:description>{3}</dc:description>\n" \
                  "{4}" \
                  "<dc:publisher>{5}</dc:publisher>\n" \
                  "<dc:rights>{6}</dc:rights>\n" \
                  "<dc:language>en-US</dc:language>\n" \
                  "<dc:date>{7}</dc:date>\n" \
                  "<dc:identifier id=\"bookid\">{0}</dc:identifier>\n" \
                  "<meta name=\"cover\" content=\"{8}\"/>\n" \
                  "</metadata>\n" \
                  "<manifest>\n" \
                  "<item id=\"ncx\" href=\"toc.ncx\" media-type=\"application/x-dtbncx+xml\" />\n" \
                  "{9}\n" \
                  "</manifest>\n" \
                  "<spine toc=\"ncx\">\n{10}</spine>\n" \
                  "<guide><reference href=\"{11}\" title=\"Cover\" type=\"cover\" /></guide>\n" \
                  "</package>"

    # Format: ID, Depth, Title, Author, NAVMAP
    TOC_NCX = "<?xml version=\"1.0\" encoding=\"utf-8\" standalone=\"no\" ?>\n" \
              "<!DOCTYPE ncx PUBLIC \"-//NISO//DTD ncx 2005-1//EN\"" \
              " \"http://www.daisy.org/z3986/2005/ncx-2005-1.dtd\">\n" \
              "<ncx xmlns=\"http://www.daisy.org/z3986/2005/ncx/\" version=\"2005-1\">\n" \
              "<head>\n" \
              "<meta content=\"ID:ISBN:{0}\" name=\"dtb:uid\"/>\n" \
              "<meta content=\"{1}\" name=\"dtb:depth\"/>\n" \
              "<meta content=\"0\" name=\"dtb:totalPageCount\"/>\n" \
              "<meta content=\"0\" name=\"dtb:maxPageNumber\"/>\n" \
              "</head>\n" \
              "<docTitle><text>{2}</text></docTitle>\n" \
              "<docAuthor><text>{3}</text></docAuthor>\n" \
              "<navMap>{4}</navMap>\n" \
              "</ncx>"

    HEADERS = {
        "Accept": "application/json, text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
        "Accept-Encoding": "gzip, deflate",
        "Referer": SAFARI_BASE_URL + "/",
        "Upgrade-Insecure-Requests": "1",
        "sec-ch-ua": "\"Google Chrome\";v=\"155\", \"Chromium\";v=\"155\", \"Not(A:Brand\";v=\"24\"",
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": "\"Linux\"",
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
                      "HeadlessChrome/155.0.0.0 Safari/537.36"
    }

    COOKIE_FLOAT_MAX_AGE_PATTERN = re.compile(r'(max-age=\d*\.\d*)', re.IGNORECASE)

    def __init__(self, args):
        self.args = args
        if getattr(args, "cookies", None):
            self.cookies_file = os.path.abspath(os.path.expanduser(args.cookies))
        else:
            self.cookies_file = COOKIES_FILE
        self.display = Display("info_%s.log" % escape(args.bookid))
        self.display.intro()

        self.session = requests.Session()
        if USE_PROXY:  # DEBUG
            self.session.proxies = PROXIES
            self.session.verify = False

        self.session.headers.update(self.HEADERS)

        self.jwt = {}

        if not args.cred:
            if not os.path.isfile(self.cookies_file):
                self.display.exit("Login: unable to find cookies file `%s`.\n"
                                  "    Please use the `--cred` or `--login` options to perform the login."
                                  % self.cookies_file)

            try:
                self.session.cookies.update(load_cookies_file(self.cookies_file))
            except ValueError as exc:
                self.display.exit("Login: %s" % exc)

        else:
            self.display.info("Logging into Safari Books Online...", state=True)
            self.do_login(*args.cred)
            if not args.no_cookies:
                json.dump(self.session.cookies.get_dict(), open(self.cookies_file, 'w'))

        self.check_login()

        self.book_id = args.bookid
        self.api_url = self.API_TEMPLATE.format(self.book_id)

        self.display.info("Retrieving book info...")
        self.book_info = self.get_book_info()
        self.display.book_info(self.book_info)

        self.display.info("Retrieving book chapters...")
        self.book_chapters = self.get_book_chapters()

        self.chapters_queue = self.book_chapters[:]

        if len(self.book_chapters) > sys.getrecursionlimit():
            sys.setrecursionlimit(len(self.book_chapters))

        self.book_title = self.book_info["title"]
        self.base_url = self.book_info["web_url"]

        self.clean_book_title = "".join(self.escape_dirname(self.book_title).split(",")[:2]) \
                                + " ({0})".format(self.book_id)

        books_dir = os.path.join(PATH, "Books")
        if not os.path.isdir(books_dir):
            os.mkdir(books_dir)

        self.BOOK_PATH = os.path.join(books_dir, self.clean_book_title)
        self.display.set_output_dir(self.BOOK_PATH)
        self.css_path = ""
        self.images_path = ""
        self.create_dirs()

        self.chapter_title = ""
        self.filename = ""
        self.chapter_stylesheets = []
        self.css = []
        self.images = []

        self.display.info("Downloading book contents... (%s chapters)" % len(self.book_chapters), state=True)
        self.BASE_HTML = self.BASE_01_HTML + (self.KINDLE_HTML if args.kindle else "") + self.BASE_02_HTML

        self.cover = False
        self.get()
        if not self.cover:
            self.cover = self.get_default_cover() if self.book_info.get("cover") else False
            if self.cover:
                cover_html = self.parse_html(
                    html.fromstring("<div id=\"sbo-rt-content\"><img src=\"Images/{0}\"></div>".format(self.cover)), True
                )

                self.book_chapters = [{
                    "filename": "default_cover.xhtml",
                    "title": "Cover"
                }] + self.book_chapters

                self.filename = self.book_chapters[0]["filename"]
                self.save_page_html(cover_html)
            else:
                self.display.log("No cover found; continuing without default cover.")

        self.css_done_queue = Queue(0) if "win" not in sys.platform else WinQueue()
        self.display.info("Downloading book CSSs... (%s files)" % len(self.css), state=True)
        self.collect_css()
        self.images_done_queue = Queue(0) if "win" not in sys.platform else WinQueue()
        self.display.info("Downloading book images... (%s files)" % len(self.images), state=True)
        self.collect_images()

        self.display.info("Creating EPUB file...", state=True)
        self.create_epub()

        if not args.no_cookies:
            json.dump(self.session.cookies.get_dict(), open(self.cookies_file, "w"))

        self.display.done(os.path.join(self.BOOK_PATH, self.book_id + ".epub"))
        self.display.unregister()

        if not self.display.in_error and not args.log:
            os.remove(self.display.log_file)

    def handle_cookie_update(self, set_cookie_headers):
        if not set_cookie_headers:
            return
        for morsel in set_cookie_headers:
            try:
                # Handle Float 'max-age' Cookie
                if self.COOKIE_FLOAT_MAX_AGE_PATTERN.search(morsel):
                    cookie_key, cookie_value = morsel.split(";")[0].split("=", 1)
                    self.session.cookies.set(cookie_key.strip(), cookie_value.strip())
            except (ValueError, AttributeError):
                continue

    def requests_provider(self, url, is_post=False, data=None, perform_redirect=True, **kwargs):
        try:
            response = getattr(self.session, "post" if is_post else "get")(
                url,
                data=data,
                allow_redirects=False,
                timeout=kwargs.pop("timeout", 30),
                **kwargs
            )

            try:
                raw_headers = response.raw.headers
                set_cookies = raw_headers.getlist("Set-Cookie") if hasattr(raw_headers, "getlist") else None
                if set_cookies is None:
                    # Fallback for urllib3 v2 / requests versions without getlist.
                    set_cookies = response.headers.get("Set-Cookie")
                    set_cookies = [set_cookies] if set_cookies else []
                self.handle_cookie_update(set_cookies)
            except Exception as exc:
                self.display.log("Cookie update skipped: %s" % exc)

            try:
                body_preview = response.text
            except Exception:
                body_preview = "<unreadable body>"
            self.display.last_request = (
                url, data, kwargs, response.status_code, "\n".join(
                    ["\t{}: {}".format(*h) for h in response.headers.items()]
                ), body_preview
            )

        except (requests.ConnectionError, requests.ConnectTimeout, requests.RequestException) as request_exception:
            self.display.error(str(request_exception))
            return 0

        if response.is_redirect and perform_redirect:
            redirect_url = response.headers.get("Location")
            if not redirect_url:
                try:
                    redirect_url = response.next.url
                except Exception:
                    redirect_url = None
            if not redirect_url:
                return response
            return self.requests_provider(urljoin(url, redirect_url), is_post, None, perform_redirect, **kwargs)

        return response

    @staticmethod
    def parse_cred(cred):
        if ":" not in cred:
            return False

        sep = cred.index(":")
        new_cred = ["", ""]
        new_cred[0] = cred[:sep].strip("'").strip('"')
        if "@" not in new_cred[0]:
            return False

        new_cred[1] = cred[sep + 1:]
        return new_cred

    def do_login(self, email, password):
        response = self.requests_provider(self.LOGIN_ENTRY_URL)
        if response == 0:
            self.display.exit("Login: unable to reach Safari Books Online. Try again...")

        next_parameter = None
        try:
            next_parameter = parse_qs(urlparse(response.request.url).query)["next"][0]

        except (AttributeError, ValueError, IndexError):
            self.display.exit("Login: unable to complete login on Safari Books Online. Try again...")

        redirect_uri = API_ORIGIN_URL + quote_plus(next_parameter)

        response = self.requests_provider(
            self.LOGIN_URL,
            is_post=True,
            json={
                "email": email,
                "password": password,
                "redirect_uri": redirect_uri
            },
            perform_redirect=False
        )

        if response == 0:
            self.display.exit("Login: unable to perform auth to Safari Books Online.\n    Try again...")

        if response.status_code != 200:  # TODO To be reviewed
            try:
                error_page = html.fromstring(response.text)
                errors_message = error_page.xpath("//ul[@class='errorlist']//li/text()")
                recaptcha = error_page.xpath("//div[@class='g-recaptcha']")
                messages = (["    `%s`" % error for error in errors_message
                             if "password" in error or "email" in error] if len(errors_message) else []) + \
                           (["    `ReCaptcha required (wait or do logout from the website).`"] if len(
                               recaptcha) else [])
                self.display.exit(
                    "Login: unable to perform auth login to Safari Books Online.\n" + self.display.SH_YELLOW +
                    "[*]" + self.display.SH_DEFAULT + " Details:\n" + "%s" % "\n".join(
                        messages if len(messages) else ["    Unexpected error!"])
                )
            except (html.etree.ParseError, html.etree.ParserError) as parsing_error:
                self.display.error(parsing_error)
                self.display.exit(
                    "Login: your login went wrong and it encountered in an error"
                    " trying to parse the login details of Safari Books Online. Try again..."
                )

        self.jwt = response.json()  # TODO: save JWT Tokens and use the refresh_token to restore user session
        response = self.requests_provider(self.jwt["redirect_uri"])
        if response == 0:
            self.display.exit("Login: unable to reach Safari Books Online. Try again...")

    def check_login(self):
        response = self.requests_provider(PROFILE_URL, perform_redirect=False)

        if response == 0:
            self.display.exit("Login: unable to reach Safari Books Online. Try again...")

        elif response.status_code != 200:
            self.display.exit("Authentication issue: unable to access profile page.")

        elif "user_type\":\"Expired\"" in response.text:
            self.display.exit("Authentication issue: account subscription expired.")

        self.display.info("Successfully authenticated.", state=True)

    def _fetch_json(self, url, what):
        response = self.requests_provider(url, headers={"Accept": "application/json"})
        if response == 0:
            self.display.exit("API: unable to retrieve %s." % what)
        if response.status_code != 200:
            try:
                payload = response.json()
            except Exception:
                payload = {"detail": "HTTP %s" % response.status_code}
            self.display.exit(self.display.api_error(payload, self.cookies_file))
        try:
            return response.json()
        except Exception as exc:
            self.display.error(str(exc))
            self.display.exit("API: unable to parse %s response." % what)

    def _fetch_paginated(self, url, what):
        results = []
        next_url = url
        while next_url:
            payload = self._fetch_json(next_url, what)
            if isinstance(payload, list):
                results.extend(payload)
                break
            batch = payload.get("results", [])
            results.extend(batch)
            next_url = payload.get("next")
        return results

    @staticmethod
    def _filename_from_reference(reference_id, ourn=""):
        if reference_id and "/" in reference_id:
            return reference_id.split("/")[-1]
        if reference_id:
            return reference_id
        if ourn:
            return ourn.split(":")[-1]
        return ""

    def get_book_info(self):
        ourn = "urn:orm:book:{0}".format(self.book_id)
        epub_url = self.EPUB_URL_TEMPLATE.format(self.book_id)
        epub = self._fetch_json(epub_url, "book info")
        if not isinstance(epub, dict) or "title" not in epub:
            self.display.exit(self.display.api_error(epub if isinstance(epub, dict) else {}, self.cookies_file))

        # Authors / publishers / web_url live in metadata + talent APIs.
        authors = []
        publishers = []
        web_url = SAFARI_BASE_URL + "/library/view/-/{0}/".format(self.book_id)
        description = ""
        subjects = []
        try:
            meta = self._fetch_json(self.METADATA_TEMPLATE.format(self.book_id), "book metadata")
            if isinstance(meta, dict) and meta.get("results"):
                m0 = meta["results"][0]
                if m0.get("description", {}).get("text/html"):
                    description = m0["description"]["text/html"]
                talent = m0.get("talent", {})
                for c in talent.get("contributors", []):
                    if c.get("name"):
                        authors.append({"name": c["name"]})
                for p in m0.get("publishers", []):
                    if p.get("name"):
                        publishers.append({"name": p["name"]})
                if m0.get("web_url"):
                    web_url = urljoin(SAFARI_BASE_URL, m0["web_url"])
                for t in m0.get("topics", []):
                    if t.get("name"):
                        subjects.append({"name": t["name"]})
        except SystemExit:
            raise
        except Exception as exc:
            self.display.log("Metadata fallback failed: %s" % exc)

        if not authors:
            try:
                talent_list = self._fetch_json(self.TALENT_TEMPLATE.format(self.book_id), "book talent")
                if isinstance(talent_list, list):
                    for c in talent_list:
                        if c.get("name"):
                            authors.append({"name": c["name"]})
            except SystemExit:
                raise
            except Exception as exc:
                self.display.log("Talent fallback failed: %s" % exc)

        if not description:
            descs = epub.get("descriptions", {}) or {}
            description = descs.get("text/html", "") or descs.get("text/plain", "")

        info = {
            "title": epub.get("title", "n/a"),
            "authors": authors or [{"name": "n/a"}],
            "identifier": epub.get("identifier", self.book_id),
            "isbn": epub.get("isbn", self.book_id),
            "publishers": publishers or [{"name": "n/a"}],
            "rights": "Copyright (c) O'Reilly Media, Inc.",
            "description": description or "n/a",
            "issued": epub.get("publication_date", "n/a"),
            "web_url": web_url,
            "subjects": subjects,
            "language": epub.get("language", "en"),
            "cover": SAFARI_BASE_URL + "/api/v2/epubs/urn:orm:book:{0}/files/assets/cover.png".format(self.book_id),
        }
        for key, value in info.items():
            if value is None:
                info[key] = "n/a"
        return info

    def get_book_chapters(self, page=1):
        # v2 uses limit/offset on spine + epub-chapters; ignore legacy page arg.
        spine_url = self.EPUB_SPINE_TEMPLATE.format(self.book_id) + "?limit=100"
        spine = self._fetch_paginated(spine_url, "book chapters")
        if not spine:
            self.display.exit("API: unable to retrieve book chapters.")

        chapters_url = self.EPUB_CHAPTERS_TEMPLATE.format(self.book_id) + "&limit=100"
        details_list = self._fetch_paginated(chapters_url, "book chapter details")
        details_by_ourn = {d.get("ourn"): d for d in details_list if d.get("ourn")}
        files_base = self.EPUB_FILES_TEMPLATE.format(self.book_id).rstrip("/")

        result = []
        for entry in spine:
            ourn = entry.get("ourn", "")
            reference_id = entry.get("reference_id", "")
            filename = self._filename_from_reference(reference_id, ourn)
            if not filename:
                continue
            title = entry.get("title", filename)
            content_url = files_base + "/" + filename
            detail = details_by_ourn.get(ourn, {})
            related = detail.get("related_assets", {}) if isinstance(detail, dict) else {}
            images = related.get("images", []) or []
            stylesheets = [{"url": u} for u in (related.get("stylesheets", []) or [])]
            result.append({
                "filename": filename,
                "title": title,
                "content": content_url,
                "asset_base_url": files_base,
                "images": images,
                "stylesheets": stylesheets,
                "site_styles": [],
            })

        if len(result) > sys.getrecursionlimit():
            sys.setrecursionlimit(len(result))

        # Keep cover first for legacy cover detection.
        covers = [c for c in result if "cover" in c["filename"].lower() or "cover" in c["title"].lower()]
        others = [c for c in result if c not in covers]
        return covers + others

    def get_default_cover(self):
        response = self.requests_provider(self.book_info["cover"], stream=True)
        if response == 0 or response.status_code != 200:
            self.display.error("Error trying to retrieve the cover: %s" % self.book_info["cover"])
            return False

        content_type = response.headers.get("Content-Type", "image/png")
        file_ext = content_type.split("/")[-1].split(";")[0].strip() or "png"
        # Normalize jpeg extension.
        if file_ext == "jpeg":
            file_ext = "jpg"
        if len(file_ext) > 4 or "/" in file_ext:
            file_ext = "png"
        with open(os.path.join(self.images_path, "default_cover." + file_ext), 'wb') as i:
            for chunk in response.iter_content(1024):
                i.write(chunk)

        return "default_cover." + file_ext

    def get_html(self, url):
        response = self.requests_provider(url)
        if response == 0 or response.status_code != 200:
            self.display.exit(
                "Crawler: error trying to retrieve this page: %s (%s)\n    From: %s" %
                (self.filename, self.chapter_title, url)
            )

        root = None
        try:
            root = html.fromstring(response.text, base_url=SAFARI_BASE_URL)

        except (html.etree.ParseError, html.etree.ParserError) as parsing_error:
            self.display.error(parsing_error)
            self.display.exit(
                "Crawler: error trying to parse this page: %s (%s)\n    From: %s" %
                (self.filename, self.chapter_title, url)
            )

        return root

    @staticmethod
    def url_is_absolute(url):
        return bool(urlparse(url).netloc)

    @staticmethod
    def is_image_link(url: str):
        return pathlib.Path(url).suffix[1:].lower() in ["jpg", "jpeg", "png", "gif"]

    def link_replace(self, link):
        if link and not link.startswith("mailto"):
            if not self.url_is_absolute(link):
                # v2 asset URLs look like /api/v2/epubs/urn:orm:book:{id}/files/assets/x.png
                if any(x in link for x in ["cover", "images", "graphics", "assets", "/api/v2/epubs/"]) or \
                        self.is_image_link(link):
                    image = link.split("/")[-1].split("?")[0].split("#")[0]
                    if image:
                        return "Images/" + image

                return link.split("?")[0].split("#")[0].replace(".html", ".xhtml")

            else:
                if self.book_id in link:
                    return self.link_replace(link.split(self.book_id)[-1])
                # Absolute v2 file URL on the same host: strip to filename.
                parsed = urlparse(link)
                if parsed.netloc.endswith("oreilly.com") and "/api/v2/epubs/" in link:
                    return self.link_replace(parsed.path)

        return link

    @staticmethod
    def get_cover(html_root):
        lowercase_ns = etree.FunctionNamespace(None)
        lowercase_ns["lower-case"] = lambda _, n: n[0].lower() if n and len(n) else ""

        images = html_root.xpath("//img[contains(lower-case(@id), 'cover') or contains(lower-case(@class), 'cover') or"
                                 "contains(lower-case(@name), 'cover') or contains(lower-case(@src), 'cover') or"
                                 "contains(lower-case(@alt), 'cover')]")
        if len(images):
            return images[0]

        divs = html_root.xpath("//div[contains(lower-case(@id), 'cover') or contains(lower-case(@class), 'cover') or"
                               "contains(lower-case(@name), 'cover') or contains(lower-case(@src), 'cover')]//img")
        if len(divs):
            return divs[0]

        a = html_root.xpath("//a[contains(lower-case(@id), 'cover') or contains(lower-case(@class), 'cover') or"
                            "contains(lower-case(@name), 'cover') or contains(lower-case(@src), 'cover')]//img")
        if len(a):
            return a[0]

        return None

    def parse_html(self, root, first_page=False):
        # NOTE: legacy random session-expiry probe removed; v2 uses JWT cookies.
        book_content = root.xpath("//div[@id='sbo-rt-content']")
        if not len(book_content):
            self.display.exit(
                "Parser: book content's corrupted or not present: %s (%s)" %
                (self.filename, self.chapter_title)
            )

        page_css = ""
        if len(self.chapter_stylesheets):
            for chapter_css_url in self.chapter_stylesheets:
                if chapter_css_url not in self.css:
                    self.css.append(chapter_css_url)
                    self.display.log("Crawler: found a new CSS at %s" % chapter_css_url)

                page_css += "<link href=\"Styles/Style{0:0>2}.css\" " \
                            "rel=\"stylesheet\" type=\"text/css\" />\n".format(self.css.index(chapter_css_url))

        stylesheet_links = root.xpath("//link[@rel='stylesheet']")
        if len(stylesheet_links):
            for s in stylesheet_links:
                css_url = urljoin("https:", s.attrib["href"]) if s.attrib["href"][:2] == "//" \
                    else urljoin(self.base_url, s.attrib["href"])

                if css_url not in self.css:
                    self.css.append(css_url)
                    self.display.log("Crawler: found a new CSS at %s" % css_url)

                page_css += "<link href=\"Styles/Style{0:0>2}.css\" " \
                            "rel=\"stylesheet\" type=\"text/css\" />\n".format(self.css.index(css_url))

        stylesheets = root.xpath("//style")
        if len(stylesheets):
            for css in stylesheets:
                if "data-template" in css.attrib and len(css.attrib["data-template"]):
                    css.text = css.attrib["data-template"]
                    del css.attrib["data-template"]

                try:
                    page_css += html.tostring(css, method="xml", encoding='unicode') + "\n"

                except (html.etree.ParseError, html.etree.ParserError) as parsing_error:
                    self.display.error(parsing_error)
                    self.display.exit(
                        "Parser: error trying to parse one CSS found in this page: %s (%s)" %
                        (self.filename, self.chapter_title)
                    )

        # TODO: add all not covered tag for `link_replace` function
        svg_image_tags = root.xpath("//image")
        if len(svg_image_tags):
            for img in svg_image_tags:
                image_attr_href = [x for x in img.attrib.keys() if "href" in x]
                if len(image_attr_href):
                    svg_url = img.attrib.get(image_attr_href[0])
                    svg_root = img.getparent().getparent()
                    new_img = svg_root.makeelement("img")
                    new_img.attrib.update({"src": svg_url})
                    svg_root.remove(img.getparent())
                    svg_root.append(new_img)

        book_content = book_content[0]
        book_content.rewrite_links(self.link_replace)

        xhtml = None
        try:
            if first_page:
                is_cover = self.get_cover(book_content)
                if is_cover is not None:
                    page_css = "<style>" \
                               "body{display:table;position:absolute;margin:0!important;height:100%;width:100%;}" \
                               "#Cover{display:table-cell;vertical-align:middle;text-align:center;}" \
                               "img{height:90vh;margin-left:auto;margin-right:auto;}" \
                               "</style>"
                    cover_html = html.fromstring("<div id=\"Cover\"></div>")
                    cover_div = cover_html.xpath("//div")[0]
                    cover_img = cover_div.makeelement("img")
                    cover_img.attrib.update({"src": is_cover.attrib["src"]})
                    cover_div.append(cover_img)
                    book_content = cover_html

                    self.cover = is_cover.attrib["src"]

            xhtml = html.tostring(book_content, method="xml", encoding='unicode')

        except (html.etree.ParseError, html.etree.ParserError) as parsing_error:
            self.display.error(parsing_error)
            self.display.exit(
                "Parser: error trying to parse HTML of this page: %s (%s)" %
                (self.filename, self.chapter_title)
            )

        return page_css, xhtml

    @staticmethod
    def escape_dirname(dirname, clean_space=False):
        if ":" in dirname:
            if dirname.index(":") > 15:
                dirname = dirname.split(":")[0]

            elif "win" in sys.platform:
                dirname = dirname.replace(":", ",")

        for ch in ['~', '#', '%', '&', '*', '{', '}', '\\', '<', '>', '?', '/', '`', '\'', '"', '|', '+', ':']:
            if ch in dirname:
                dirname = dirname.replace(ch, "_")

        return dirname if not clean_space else dirname.replace(" ", "")

    def create_dirs(self):
        if os.path.isdir(self.BOOK_PATH):
            self.display.log("Book directory already exists: %s" % self.BOOK_PATH)

        else:
            os.makedirs(self.BOOK_PATH)

        oebps = os.path.join(self.BOOK_PATH, "OEBPS")
        if not os.path.isdir(oebps):
            self.display.book_ad_info = True
            os.makedirs(oebps)

        self.css_path = os.path.join(oebps, "Styles")
        if os.path.isdir(self.css_path):
            self.display.log("CSSs directory already exists: %s" % self.css_path)

        else:
            os.makedirs(self.css_path)
            self.display.css_ad_info.value = 1

        self.images_path = os.path.join(oebps, "Images")
        if os.path.isdir(self.images_path):
            self.display.log("Images directory already exists: %s" % self.images_path)

        else:
            os.makedirs(self.images_path)
            self.display.images_ad_info.value = 1

    def save_page_html(self, contents):
        self.filename = self.filename.replace(".html", ".xhtml")
        open(os.path.join(self.BOOK_PATH, "OEBPS", self.filename), "wb") \
            .write(self.BASE_HTML.format(contents[0], contents[1]).encode("utf-8", 'xmlcharrefreplace'))
        self.display.log("Created: %s" % self.filename)

    def get(self):
        len_books = len(self.book_chapters)

        for _ in range(len_books):
            if not len(self.chapters_queue):
                return

            first_page = len_books == len(self.chapters_queue)

            next_chapter = self.chapters_queue.pop(0)
            self.chapter_title = next_chapter["title"]
            self.filename = next_chapter["filename"]

            asset_base_url = next_chapter.get('asset_base_url', "")
            api_v2_detected = 'v2' in next_chapter.get('content', "")

            if "images" in next_chapter and len(next_chapter["images"]):
                for img_url in next_chapter['images']:
                    if not img_url:
                        continue
                    # v2 related_assets are absolute URLs; keep them as-is.
                    if self.url_is_absolute(img_url):
                        self.images.append(img_url)
                    elif api_v2_detected:
                        base = SAFARI_BASE_URL + "/api/v2/epubs/urn:orm:book:{}/files".format(self.book_id)
                        # img_url may be a bare filename from legacy data.
                        if img_url.startswith("assets/") or "/" not in img_url:
                            self.images.append(base + '/' + img_url.lstrip("/"))
                        else:
                            self.images.append(urljoin(base + "/", img_url))
                    else:
                        self.images.append(urljoin(next_chapter['asset_base_url'], img_url))


            # Stylesheets (v2 gives list of {"url": ...} or plain strings)
            self.chapter_stylesheets = []
            if "stylesheets" in next_chapter and len(next_chapter["stylesheets"]):
                for entry in next_chapter["stylesheets"]:
                    if isinstance(entry, dict):
                        url = entry.get("url", "")
                    else:
                        url = entry
                    if url:
                        self.chapter_stylesheets.append(url)

            if "site_styles" in next_chapter and len(next_chapter["site_styles"]):
                for entry in next_chapter["site_styles"]:
                    if isinstance(entry, dict):
                        url = entry.get("url", "")
                    else:
                        url = entry
                    if url:
                        self.chapter_stylesheets.append(url)

            if os.path.isfile(os.path.join(self.BOOK_PATH, "OEBPS", self.filename.replace(".html", ".xhtml"))):
                if not self.display.book_ad_info and \
                        next_chapter not in self.book_chapters[:self.book_chapters.index(next_chapter)]:
                    self.display.info(
                        ("File `%s` already exists.\n"
                         "    If you want to download again all the book,\n"
                         "    please delete the output directory '" + self.BOOK_PATH + "' and restart the program.")
                         % self.filename.replace(".html", ".xhtml")
                    )
                    self.display.book_ad_info = 2

            else:
                self.save_page_html(self.parse_html(self.get_html(next_chapter["content"]), first_page))

            self.display.state(len_books, len_books - len(self.chapters_queue))

    def _thread_download_css(self, url):
        css_file = os.path.join(self.css_path, "Style{0:0>2}.css".format(self.css.index(url)))
        if os.path.isfile(css_file):
            if not self.display.css_ad_info.value and url not in self.css[:self.css.index(url)]:
                self.display.info(("File `%s` already exists.\n"
                                   "    If you want to download again all the CSSs,\n"
                                   "    please delete the output directory '" + self.BOOK_PATH + "'"
                                   " and restart the program.") %
                                  css_file)
                self.display.css_ad_info.value = 1

        else:
            response = self.requests_provider(url)
            if response == 0 or response.status_code != 200:
                self.display.error("Error trying to retrieve this CSS: %s\n    From: %s" % (css_file, url))
                self.css_done_queue.put(1)
                self.display.state(len(self.css), self.css_done_queue.qsize())
                return

            with open(css_file, 'wb') as s:
                s.write(response.content)

        self.css_done_queue.put(1)
        self.display.state(len(self.css), self.css_done_queue.qsize())


    def _thread_download_images(self, url):
        image_name = url.split("/")[-1].split("?")[0].split("#")[0]
        if not image_name:
            self.display.error("Error trying to retrieve this image (empty name): %s" % url)
            return
        image_path = os.path.join(self.images_path, image_name)
        if os.path.isfile(image_path):
            if not self.display.images_ad_info.value and url not in self.images[:self.images.index(url)]:
                self.display.info(("File `%s` already exists.\n"
                                   "    If you want to download again all the images,\n"
                                   "    please delete the output directory '" + self.BOOK_PATH + "'"
                                   " and restart the program.") %
                                  image_name)
                self.display.images_ad_info.value = 1

        else:
            # urljoin keeps absolute https URLs; resolves /api/... against host.
            fetch_url = url if self.url_is_absolute(url) else urljoin(SAFARI_BASE_URL, url)
            response = self.requests_provider(fetch_url, stream=True)
            if response == 0 or response.status_code != 200:
                self.display.error("Error trying to retrieve this image: %s\n    From: %s" % (image_name, url))
                self.images_done_queue.put(1)
                self.display.state(len(self.images), self.images_done_queue.qsize())
                return

            with open(image_path, 'wb') as img:
                for chunk in response.iter_content(1024):
                    img.write(chunk)

        self.images_done_queue.put(1)
        self.display.state(len(self.images), self.images_done_queue.qsize())

    def _start_multiprocessing(self, operation, full_queue):
        if len(full_queue) > 5:
            for i in range(0, len(full_queue), 5):
                self._start_multiprocessing(operation, full_queue[i:i + 5])

        else:
            process_queue = [Process(target=operation, args=(arg,)) for arg in full_queue]
            for proc in process_queue:
                proc.start()

            for proc in process_queue:
                proc.join()

    def collect_css(self):
        self.display.state_status.value = -1

        # "self._start_multiprocessing" seems to cause problem. Switching to mono-thread download.
        for css_url in self.css:
            self._thread_download_css(css_url)

    def collect_images(self):
        if self.display.book_ad_info == 2:
            self.display.info("Some of the book contents were already downloaded.\n"
                              "    If you want to be sure that all the images will be downloaded,\n"
                              "    please delete the output directory '" + self.BOOK_PATH +
                              "' and restart the program.")

        self.display.state_status.value = -1

        # "self._start_multiprocessing" seems to cause problem. Switching to mono-thread download.
        for image_url in self.images:
            self._thread_download_images(image_url)

    def create_content_opf(self):
        self.css = next(os.walk(self.css_path))[2]
        self.images = next(os.walk(self.images_path))[2]

        manifest = []
        spine = []
        for c in self.book_chapters:
            c["filename"] = c["filename"].replace(".html", ".xhtml")
            item_id = escape("".join(c["filename"].split(".")[:-1]))
            manifest.append("<item id=\"{0}\" href=\"{1}\" media-type=\"application/xhtml+xml\" />".format(
                item_id, c["filename"]
            ))
            spine.append("<itemref idref=\"{0}\"/>".format(item_id))

        for i in set(self.images):
            dot_split = i.split(".")
            head = "img_" + escape("".join(dot_split[:-1]))
            extension = dot_split[-1]
            manifest.append("<item id=\"{0}\" href=\"Images/{1}\" media-type=\"image/{2}\" />".format(
                head, i, "jpeg" if "jp" in extension else extension
            ))

        for i in range(len(self.css)):
            manifest.append("<item id=\"style_{0:0>2}\" href=\"Styles/Style{0:0>2}.css\" "
                            "media-type=\"text/css\" />".format(i))

        authors = "\n".join("<dc:creator opf:file-as=\"{0}\" opf:role=\"aut\">{0}</dc:creator>".format(
            escape(aut.get("name", "n/d"))
        ) for aut in self.book_info.get("authors", []))

        subjects = "\n".join("<dc:subject>{0}</dc:subject>".format(escape(sub.get("name", "n/d")))
                             for sub in self.book_info.get("subjects", []))

        return self.CONTENT_OPF.format(
            (self.book_info.get("isbn",  self.book_id)),
            escape(self.book_title),
            authors,
            escape(self.book_info.get("description", "")),
            subjects,
            ", ".join(escape(pub.get("name", "")) for pub in self.book_info.get("publishers", [])),
            escape(self.book_info.get("rights", "")),
            self.book_info.get("issued", ""),
            escape(str(self.cover)) if self.cover else "cover",
            "\n".join(manifest),
            "\n".join(spine),
            self.book_chapters[0]["filename"].replace(".html", ".xhtml")
        )

    @staticmethod
    def _normalize_toc_entry(entry):
        # Accept both v1 (label/href/id) and v2 (title/reference_id/ourn) shapes.
        if "label" in entry or "href" in entry or "id" in entry:
            return entry
        reference_id = entry.get("reference_id", "")
        filename = reference_id.split("/")[-1] if "/" in reference_id else reference_id
        if not filename and entry.get("ourn"):
            filename = entry["ourn"].split(":")[-1]
        return {
            "depth": entry.get("depth", 1),
            "label": entry.get("title", filename),
            "href": filename or "index.html",
            "fragment": entry.get("fragment", ""),
            "id": entry.get("ourn", "") or entry.get("fragment", "") or filename,
            "children": [SafariBooks._normalize_toc_entry(c) for c in (entry.get("children") or [])],
        }

    @staticmethod
    def parse_toc(l, c=0, mx=0):
        r = ""
        for raw in l:
            cc = SafariBooks._normalize_toc_entry(raw) if "label" not in raw else raw
            c += 1
            try:
                depth = int(cc.get("depth", 1))
            except (TypeError, ValueError):
                depth = 1
            if depth > mx:
                mx = depth

            node_id = cc.get("fragment") or cc.get("id") or "ch%d" % c
            filename = (cc.get("href", "") or "").replace(".html", ".xhtml").split("/")[-1]
            fragment = cc.get("fragment", "")
            # Preserve in-page anchors like upstream toc.ncx (file.html#fragment).
            if fragment and "#" not in filename:
                # Avoid duplicating when filename already is a bare anchor.
                content_src = "%s#%s" % (filename, fragment) if filename else "#%s" % fragment
                # Top-level entries whose fragment is a section id still resolve
                # inside the same file; child entries share the parent file.
                # If fragment equals the file stem heuristic, keep file-only for
                # the top node to match legacy behaviour? No: upstream includes it.
            else:
                content_src = filename
            r += "<navPoint id=\"{0}\" playOrder=\"{1}\">" \
                 "<navLabel><text>{2}</text></navLabel>" \
                 "<content src=\"{3}\"/>".format(
                    escape(str(node_id)), c,
                    escape(str(cc.get("label", ""))), escape(content_src)
                 )

            children = cc.get("children") or []
            if children:
                sr, c, mx = SafariBooks.parse_toc(children, c, mx)
                r += sr

            r += "</navPoint>\n"

        return r, c, mx

    def create_toc(self):
        toc_url = self.EPUB_TOC_TEMPLATE.format(self.book_id)
        response = self.requests_provider(toc_url, headers={"Accept": "application/json"})
        if response == 0:
            self.display.exit("API: unable to retrieve book chapters. "
                              "Don't delete any files, just run again this program"
                              " in order to complete the `.epub` creation!")

        try:
            payload = response.json()
        except Exception as exc:
            self.display.error(str(exc))
            self.display.exit("API: unable to retrieve book chapters. "
                              "Don't delete any files, just run again this program"
                              " in order to complete the `.epub` creation!")

        if isinstance(payload, dict):
            if "results" in payload:
                toc = payload["results"]
            elif len(payload.keys()) == 1:
                self.display.exit(
                    self.display.api_error(payload, self.cookies_file) +
                    " Don't delete any files, just run again this program"
                    " in order to complete the `.epub` creation!"
                )
            else:
                self.display.exit("API: unexpected table-of-contents format.")
        elif isinstance(payload, list):
            toc = payload
        else:
            self.display.exit("API: unexpected table-of-contents format.")

        navmap, _, max_depth = self.parse_toc(toc)
        return self.TOC_NCX.format(
            (self.book_info["isbn"] if self.book_info["isbn"] else self.book_id),
            max_depth,
            self.book_title,
            ", ".join(aut.get("name", "") for aut in self.book_info.get("authors", [])),
            navmap
        )

    def create_epub(self):
        open(os.path.join(self.BOOK_PATH, "mimetype"), "w").write("application/epub+zip")
        meta_info = os.path.join(self.BOOK_PATH, "META-INF")
        if os.path.isdir(meta_info):
            self.display.log("META-INF directory already exists: %s" % meta_info)

        else:
            os.makedirs(meta_info)

        open(os.path.join(meta_info, "container.xml"), "wb").write(
            self.CONTAINER_XML.encode("utf-8", "xmlcharrefreplace")
        )
        open(os.path.join(self.BOOK_PATH, "OEBPS", "content.opf"), "wb").write(
            self.create_content_opf().encode("utf-8", "xmlcharrefreplace")
        )
        open(os.path.join(self.BOOK_PATH, "OEBPS", "toc.ncx"), "wb").write(
            self.create_toc().encode("utf-8", "xmlcharrefreplace")
        )

        zip_file = os.path.join(PATH, "Books", self.book_id)
        if os.path.isfile(zip_file + ".zip"):
            os.remove(zip_file + ".zip")

        shutil.make_archive(zip_file, 'zip', self.BOOK_PATH)
        os.rename(zip_file + ".zip", os.path.join(self.BOOK_PATH, self.book_id) + ".epub")


# MAIN
if __name__ == "__main__":
    arguments = argparse.ArgumentParser(prog="safaribooks.py",
                                        description="Download and generate an EPUB of your favorite books"
                                                    " from Safari Books Online.",
                                        add_help=False,
                                        allow_abbrev=False)

    login_arg_group = arguments.add_mutually_exclusive_group()
    login_arg_group.add_argument(
        "--cred", metavar="<EMAIL:PASS>", default=False,
        help="Credentials used to perform the auth login on Safari Books Online."
             " Es. ` --cred \"account_mail@mail.com:password01\" `."
    )
    login_arg_group.add_argument(
        "--login", action='store_true',
        help="Prompt for credentials used to perform the auth login on Safari Books Online."
    )

    arguments.add_argument(
        "--no-cookies", dest="no_cookies", action='store_true',
        help="Prevent your session data to be saved into `cookies.json` file."
    )
    arguments.add_argument(
        "--cookies", metavar="<PATH>", dest="cookies", default=None,
        help="Path to the `cookies.json` session file. Defaults to `cookies.json`"
             " next to the program."
    )
    arguments.add_argument(
        "--kindle", dest="kindle", action='store_true',
        help="Add some CSS rules that block overflow on `table` and `pre` elements."
             " Use this option if you're going to export the EPUB to E-Readers like Amazon Kindle."
    )
    arguments.add_argument(
        "--preserve-log", dest="log", action='store_true', help="Leave the `info_XXXXXXXXXXXXX.log`"
                                                                " file even if there isn't any error."
    )
    arguments.add_argument("--help", action="help", default=argparse.SUPPRESS, help='Show this help message.')
    arguments.add_argument(
        "bookid", metavar='<BOOK ID>',
        help="Book digits ID that you want to download. You can find it in the URL (X-es):"
             " `" + SAFARI_BASE_URL + "/library/view/book-name/XXXXXXXXXXXXX/`"
    )

    args_parsed = arguments.parse_args()
    if args_parsed.cred or args_parsed.login:
        print("WARNING: Due to recent changes on ORLY website, \n" \
                "the `--cred` and `--login` options are temporarily disabled.\n"
                "    Please use the `cookies.json` file to authenticate your account.\n"
                "    See: https://github.com/lorenzodifuccia/safaribooks/issues/358")
        arguments.exit()
        
        # user_email = ""
        # pre_cred = ""

        # if args_parsed.cred:
        #     pre_cred = args_parsed.cred

        # else:
        #     user_email = input("Email: ")
        #     passwd = getpass.getpass("Password: ")
        #     pre_cred = user_email + ":" + passwd

        # parsed_cred = SafariBooks.parse_cred(pre_cred)

        # if not parsed_cred:
        #     arguments.error("invalid credential: %s" % (
        #         args_parsed.cred if args_parsed.cred else (user_email + ":*******")
        #     ))

        # args_parsed.cred = parsed_cred

    else:
        if args_parsed.no_cookies:
            arguments.error("invalid option: `--no-cookies` is valid only if you use the `--cred` option")

    SafariBooks(args_parsed)
    # Hint: do you want to download more then one book once, initialized more than one instance of `SafariBooks`...
    sys.exit(0)
