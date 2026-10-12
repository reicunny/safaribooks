"""Regression tests for safaribooks.

Covers the two fixed download blockers plus nearby helpers:

* non-ASCII (e.g. Polish ``ł``) author names on Windows/cp1252 systems
  (log file must stay UTF-8, console output must degrade, not crash),
* v2 chapter ``/files/`` URLs must keep the archive subdir
  (``.../files/Text/titlepage.xhtml``, not basename-only ``.../files/titlepage.xhtml``),
* helpers: TOC normalize/parse, link rewriting, dirname escaping,
  cookies.json loading.

Stdlib ``unittest`` only -- run with::

    python -m unittest discover -s tests -v
"""

import contextlib
import io
import json
import logging
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import safaribooks
from safaribooks import Display, SafariBooks, load_cookies_file


class DisplayMixin:
    """Create Display instances writing to a temp dir, with reliable cleanup.

    Display registers on the shared ``SafariBooks`` logger and overrides
    ``sys.excepthook``; both are undone here so tests stay isolated and log
    files are never left locked (matters on Windows).
    """

    def make_display(self, name="test.log"):
        self._old_excepthook = sys.excepthook
        log_path = os.path.join(self.tmpdir, name)
        disp = Display(log_path)
        # Display joins PATH with the name; an absolute temp path wins.
        self.assertTrue(os.path.isfile(disp.log_file), disp.log_file)
        handler = disp.logger.handlers[-1]
        self._displays.append((disp, handler))
        return disp

    def tearDown_display(self):
        for disp, handler in reversed(getattr(self, "_displays", [])):
            try:
                disp.logger.removeHandler(handler)
            finally:
                try:
                    handler.close()
                except Exception:
                    pass
        self._displays = []
        if hasattr(self, "_old_excepthook"):
            sys.excepthook = self._old_excepthook


class PathFromReferenceTests(unittest.TestCase):
    def test_strips_bookid_prefix_but_keeps_subdir(self):
        self.assertEqual(
            SafariBooks._path_from_reference("9781633436305-/Text/titlepage.xhtml", ""),
            "Text/titlepage.xhtml",
        )
        self.assertEqual(
            SafariBooks._path_from_reference("9783112223772-/content/cover.xhtml", ""),
            "content/cover.xhtml",
        )

    def test_filename_is_basename_of_path(self):
        self.assertEqual(
            SafariBooks._filename_from_reference("9781633436305-/Text/titlepage.xhtml", ""),
            "titlepage.xhtml",
        )
        self.assertEqual(
            SafariBooks._filename_from_reference("9783112223772-/content/cover.xhtml", ""),
            "cover.xhtml",
        )

    def test_plain_references_pass_through(self):
        self.assertEqual(SafariBooks._path_from_reference("plain.html", ""), "plain.html")
        self.assertEqual(SafariBooks._filename_from_reference("Text/copyright.html", ""), "copyright.html")

    def test_empty_inputs(self):
        self.assertEqual(SafariBooks._path_from_reference("", ""), "")
        self.assertEqual(SafariBooks._filename_from_reference("", ""), "")


class GetBookChaptersUrlTests(unittest.TestCase):
    BOOK_ID = "9781633436305"
    FILES = "https://learning.oreilly.com/api/v2/epubs/urn:orm:book:9781633436305/files"

    def _chapter_obj(self, spine, details):
        obj = SafariBooks.__new__(SafariBooks)
        obj.book_id = self.BOOK_ID
        obj.display = mock.MagicMock()

        def fake_fetch(url, what):
            return details if "epub-chapters" in url else spine

        obj._fetch_paginated = fake_fetch
        return obj

    def test_prefers_api_content_url(self):
        spine = [{
            "ourn": "urn:orm:book:9781633436305:chapter:Text%2ftitlepage.xhtml",
            "reference_id": "9781633436305-/Text/titlepage.xhtml",
            "title": "Cover",
        }]
        details = [{
            "ourn": "urn:orm:book:9781633436305:chapter:Text%2ftitlepage.xhtml",
            "content_url": self.FILES + "/Text/titlepage.xhtml",
            "related_assets": {"images": [], "stylesheets": []},
        }]
        chapters = SafariBooks.get_book_chapters(self._chapter_obj(spine, details))
        self.assertEqual(len(chapters), 1)
        self.assertEqual(chapters[0]["filename"], "titlepage.xhtml")
        self.assertEqual(chapters[0]["content"], self.FILES + "/Text/titlepage.xhtml")

    def test_fallback_rebuilds_subdir_path(self):
        # No content_url in the detail: must still keep Text/, never basename-only.
        spine = [{
            "ourn": "urn:orm:book:9781633436305:chapter:Text%2fchapter-1.html",
            "reference_id": "9781633436305-/Text/chapter-1.html",
            "title": "Ch 1",
        }]
        details = [{
            "ourn": "urn:orm:book:9781633436305:chapter:Text%2fchapter-1.html",
            "related_assets": {"images": [], "stylesheets": []},
        }]
        chapters = SafariBooks.get_book_chapters(self._chapter_obj(spine, details))
        self.assertEqual(chapters[0]["content"], self.FILES + "/Text/chapter-1.html")
        self.assertNotEqual(chapters[0]["content"], self.FILES + "/chapter-1.html")

    def test_basename_only_url_is_never_produced(self):
        # Regression: basename-only .../files/titlepage.xhtml 404s with
        # "No EpubFile matches the given query."
        spine = [{
            "ourn": "urn:orm:book:9781633436305:chapter:Text%2ftitlepage.xhtml",
            "reference_id": "9781633436305-/Text/titlepage.xhtml",
            "title": "Cover",
        }]
        chapters = SafariBooks.get_book_chapters(self._chapter_obj(spine, []))
        for chapter in chapters:
            self.assertNotRegex(chapter["content"], r"/files/[^/]+\.x?html$")


class UnicodeDisplayTests(DisplayMixin, unittest.TestCase):
    AUTHORS = "Authors: Władysław Homenda, Witold Pedrycz"

    def setUp(self):
        self._displays = []
        self._tmp = tempfile.TemporaryDirectory()
        self.tmpdir = self._tmp.name

    def tearDown(self):
        self.tearDown_display()
        self._tmp.cleanup()
        # Display uses a shared logger; drop stale closed handlers.
        logger = logging.getLogger("SafariBooks")
        logger.handlers = [h for h in logger.handlers if not getattr(h, "stream", None) or not h.stream.closed]

    def test_log_handler_is_utf8(self):
        disp = self.make_display()
        self.assertEqual(disp.logger.handlers[-1].encoding, "utf-8")

    def test_log_polish_authors_without_logging_error(self):
        disp = self.make_display()
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            disp.log(self.AUTHORS)
            disp.log(self.AUTHORS.encode("utf-8"))  # bytes input still decodes
        stderr = err.getvalue()
        self.assertNotIn("Logging error", stderr)
        self.assertNotIn("UnicodeEncodeError", stderr)
        with open(disp.log_file, encoding="utf-8") as f:
            content = f.read()
        self.assertIn("Władysław Homenda", content)
        self.assertIn("Witold Pedrycz", content)

    def test_out_survives_cp1252_console(self):
        disp = self.make_display()
        buf = io.BytesIO()
        fake = io.TextIOWrapper(buf, encoding="cp1252", errors="strict")
        real_stdout = sys.stdout
        sys.stdout = fake
        try:
            disp.out(self.AUTHORS)  # must not raise; ł becomes ?
            disp.out(self.AUTHORS.encode("utf-8"))
            fake.flush()
        finally:
            sys.stdout = real_stdout
        text = buf.getvalue().decode("cp1252", "replace")
        self.assertIn("Homenda", text)
        self.assertIn("Witold Pedrycz", text)

    def test_book_info_with_polish_authors(self):
        disp = self.make_display()
        info = {
            "title": "Automata Theory and Formal Languages, 2nd Edition",
            "authors": [{"name": "Władysław Homenda"}, {"name": "Witold Pedrycz"}],
            "identifier": "9783112223772",
            "isbn": "9783112223772",
            "publishers": [{"name": "De Gruyter"}],
            "rights": "Copyright",
            "description": "Test",
            "issued": "2025-01-01",
            "web_url": "https://learning.oreilly.com/library/view/-/9783112223772/",
        }
        err = io.StringIO()
        out = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
            disp.book_info(info)
        stderr = err.getvalue()
        self.assertNotIn("Logging error", stderr)
        self.assertNotIn("UnicodeEncodeError", stderr)
        with open(disp.log_file, encoding="utf-8") as f:
            self.assertIn("Władysław Homenda", f.read())


class CookieFileTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmpdir = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def _write(self, name, data, encoding="utf-8"):
        path = os.path.join(self.tmpdir, name)
        if isinstance(data, bytes):
            with open(path, "wb") as f:
                f.write(data)
        else:
            with open(path, "w", encoding=encoding) as f:
                f.write(data)
        return path

    def test_dict_format(self):
        path = self._write("c.json", json.dumps({"orm-jwt": "a", "orm-rt": "b"}))
        self.assertEqual(load_cookies_file(path), {"orm-jwt": "a", "orm-rt": "b"})

    def test_list_format(self):
        payload = [{"name": "orm-jwt", "value": "a"}, {"name": "orm-rt", "value": "b"}]
        path = self._write("c.json", json.dumps(payload))
        self.assertEqual(load_cookies_file(path), {"orm-jwt": "a", "orm-rt": "b"})

    def test_doubly_stringified(self):
        inner = json.dumps({"orm-jwt": "a"})
        path = self._write("c.json", json.dumps(inner))
        self.assertEqual(load_cookies_file(path), {"orm-jwt": "a"})

    def test_bom_is_accepted(self):
        import codecs
        path = self._write("c.json", codecs.BOM_UTF8 + json.dumps({"orm-jwt": "a"}).encode("utf-8"))
        self.assertEqual(load_cookies_file(path), {"orm-jwt": "a"})

    def test_values_normalized_to_str(self):
        path = self._write("c.json", json.dumps({"n": 123, "": "dropped", "orm-jwt": "a"}))
        self.assertEqual(load_cookies_file(path), {"n": "123", "orm-jwt": "a"})

    def test_empty_file_rejected(self):
        path = self._write("c.json", "   ")
        with self.assertRaises(ValueError):
            load_cookies_file(path)

    def test_truncated_json_rejected_with_hint(self):
        path = self._write("c.json", '{"orm-jwt": "abc')
        with self.assertRaises(ValueError):
            load_cookies_file(path)

    def test_bad_list_entry_rejected(self):
        path = self._write("c.json", json.dumps([{"oops": 1}]))
        with self.assertRaises(ValueError):
            load_cookies_file(path)


class TocTests(unittest.TestCase):
    def test_normalize_passes_v1_through(self):
        entry = {"label": "L", "href": "f.html", "id": "1", "depth": 2, "children": []}
        self.assertIs(SafariBooks._normalize_toc_entry(entry), entry)

    def test_normalize_converts_v2_reference_id(self):
        entry = {
            "depth": 1,
            "reference_id": "9781633436305-/Text/chapter-1.html",
            "ourn": "urn:orm:book:9781633436305:chapter:Text%2fchapter-1.html",
            "fragment": "",
            "title": "Ch 1",
            "children": [],
        }
        norm = SafariBooks._normalize_toc_entry(entry)
        self.assertEqual(norm["href"], "chapter-1.html")
        self.assertEqual(norm["label"], "Ch 1")

    def test_parse_toc_keeps_fragment_anchor(self):
        entry = {
            "depth": 1,
            "reference_id": "9781633436305-/Text/chapter-1.html",
            "ourn": "urn:orm:book:9781633436305:chapter:Text%2fchapter-1.html",
            "fragment": "sec1",
            "title": "Ch 1",
            "children": [],
        }
        navmap, count, max_depth = SafariBooks.parse_toc([entry])
        self.assertIn("chapter-1.xhtml#sec1", navmap)
        self.assertEqual((count, max_depth), (1, 1))

    def test_parse_toc_escapes_xml(self):
        entry = {"label": "A&B <C>", "href": "f.html", "id": "1", "depth": 1, "children": []}
        navmap, _, _ = SafariBooks.parse_toc([entry])
        self.assertIn("A&amp;B", navmap)
        self.assertNotIn("A&B ", navmap)


class LinkReplaceTests(unittest.TestCase):
    def setUp(self):
        self.obj = SafariBooks.__new__(SafariBooks)
        self.obj.book_id = "9781633436305"

    def test_bare_image_name_maps_to_images_dir(self):
        self.assertEqual(self.obj.link_replace("cover.jpg"), "Images/cover.jpg")

    def test_chapter_html_becomes_xhtml(self):
        self.assertEqual(self.obj.link_replace("chapter-1.html"), "chapter-1.xhtml")

    def test_mailto_untouched(self):
        self.assertEqual(self.obj.link_replace("mailto:a@b.c"), "mailto:a@b.c")

    def test_external_links_untouched(self):
        url = "https://example.com/other/page.html"
        self.assertEqual(self.obj.link_replace(url), url)

    def test_url_helpers(self):
        self.assertTrue(SafariBooks.url_is_absolute("https://x.com/y"))
        self.assertFalse(SafariBooks.url_is_absolute("/rel/path"))
        self.assertTrue(SafariBooks.is_image_link("a.JPG"))
        self.assertFalse(SafariBooks.is_image_link("a.html"))


class EscapeDirnameTests(unittest.TestCase):
    def test_forbidden_chars_replaced(self):
        result = SafariBooks.escape_dirname("A/B?D*E")
        for ch in ("~", "#", "%", "&", "*", "{", "}", "\\", "<", ">", "?", "/", "`", "'", '"', "|", "+"):
            self.assertNotIn(ch, result)

    def test_colon_never_survives(self):
        self.assertNotIn(":", SafariBooks.escape_dirname("Short: Title"))
        self.assertNotIn(":", SafariBooks.escape_dirname("A Very Long Title Prefix: Sub"))


class BatchIdsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmpdir = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def _write_bytes(self, name, data):
        path = os.path.join(self.tmpdir, name)
        with open(path, "wb") as f:
            f.write(data)
        return path

    def test_multiple_ids_pass_through(self):
        from safaribooks import collect_book_ids
        self.assertEqual(
            collect_book_ids(["0642572230302", "9798341623590", "9781836207474"]),
            ["0642572230302", "9798341623590", "9781836207474"],
        )

    def test_duplicates_removed_preserving_order(self):
        from safaribooks import collect_book_ids
        self.assertEqual(
            collect_book_ids(["0642572230302", "9781836207474", "0642572230302"]),
            ["0642572230302", "9781836207474"],
        )

    def test_ids_file_lf(self):
        from safaribooks import collect_book_ids, load_ids_from_file
        path = self._write_bytes("IDs_LF.txt", b"0642572230302\n9781836207474\n9781836207474\n")
        self.assertEqual(
            load_ids_from_file(path),
            ["0642572230302", "9781836207474", "9781836207474"],
        )
        # collect_* de-duplicates the repeated line from the example.
        self.assertEqual(collect_book_ids([path]), ["0642572230302", "9781836207474"])

    def test_ids_file_crlf(self):
        from safaribooks import load_ids_from_file
        path = self._write_bytes("IDs_CRLF.txt", b"0642572230302\r\n9781836207474\r\n9781836207474\r\n")
        self.assertEqual(
            load_ids_from_file(path),
            ["0642572230302", "9781836207474", "9781836207474"],
        )

    def test_ids_file_cr_only(self):
        from safaribooks import load_ids_from_file
        path = self._write_bytes("IDs_CR.txt", b"0642572230302\r9781836207474\r9781836207474\r")
        self.assertEqual(
            load_ids_from_file(path),
            ["0642572230302", "9781836207474", "9781836207474"],
        )

    def test_ids_file_skips_blank_and_whitespace(self):
        from safaribooks import collect_book_ids
        path = self._write_bytes("IDs_mix.txt", b"  0642572230302  \r\n\n   \r\n9781836207474\r\n")
        self.assertEqual(collect_book_ids([path]), ["0642572230302", "9781836207474"])

    def test_mixed_cli_and_file(self):
        from safaribooks import collect_book_ids
        path = self._write_bytes("IDs.txt", b"9781836207474\n")
        self.assertEqual(
            collect_book_ids(["0642572230302", path, "9798341623590", path]),
            ["0642572230302", "9781836207474", "9798341623590"],
        )

    def test_missing_txt_file_rejected(self):
        from safaribooks import collect_book_ids
        with self.assertRaises(ValueError):
            collect_book_ids([os.path.join(self.tmpdir, "missing.txt")])

    def test_empty_ids_file_rejected(self):
        from safaribooks import collect_book_ids
        path = self._write_bytes("empty.txt", b"  \n \r\n")
        with self.assertRaises(ValueError):
            collect_book_ids([path])

    def test_no_ids_rejected(self):
        from safaribooks import collect_book_ids
        with self.assertRaises(ValueError):
            collect_book_ids([])


if __name__ == "__main__":
    unittest.main()
