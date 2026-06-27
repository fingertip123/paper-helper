#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import sys
import tempfile
import shutil
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

import bib_io


class TestBibIo(unittest.TestCase):
    def testParseBibtexEntries(self):
        stext = """
@article{smith2020,
  author = {Smith, John and Doe, Jane},
  title = {A Great Paper},
  year = {2020},
  journal = {Nature},
  doi = {10.1038/test}
}
"""
        ventries = bib_io.ParseBibtexEntries(stext)
        self.assertEqual(len(ventries), 1)
        self.assertEqual(ventries[0]["_citekey"], "smith2020")
        self.assertIn("Smith", ventries[0]["author"])
        self.assertEqual(ventries[0]["year"], "2020")

    def testFormatCitationText(self):
        scite = bib_io.FormatCitationText("smith-2020", "Title", ["Smith, John", "Doe, Jane"], "2020")
        self.assertEqual(scite, "(Smith et al., 2020) [[smith-2020]]")

    def testImportBibtexCreateAndUpdate(self):
        otmp = tempfile.mkdtemp()
        owiki = os.path.join(otmp, "wiki")
        os.makedirs(os.path.join(owiki, "sources"))
        try:
            spath = os.path.join(owiki, "sources", "smith-2020.md")
            with open(spath, "w", encoding="utf-8") as f:
                f.write("---\ntype: source\ntitle: Old\nsources: [smith-2020]\n---\n\n# Old\n")
            stext = """
@article{smith-2020,
  author = {Smith, John},
  title = {Updated Title},
  year = {2020},
  journal = {Science}
}
@inproceedings{lee2021,
  author = {Lee, Amy},
  title = {New Paper},
  year = {2021},
  booktitle = {ICML}
}
"""
            oresult = bib_io.ImportBibtex(stext, owiki)
            self.assertEqual(oresult["total"], 2)
            self.assertIn("smith-2020", oresult["updated"])
            self.assertIn("lee2021", oresult["created"])
            with open(spath, "r", encoding="utf-8") as f:
                sbody = f.read()
            self.assertIn("Updated Title", sbody)
            self.assertTrue(os.path.isfile(os.path.join(owiki, "sources", "lee2021.md")))
        finally:
            shutil.rmtree(otmp)


if __name__ == "__main__":
    unittest.main()
