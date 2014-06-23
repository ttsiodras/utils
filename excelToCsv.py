#!/usr/local/bin/python
# -*- coding: utf-8 -*-

"""
A script I hacked quickly, to easily peek into Excel (.xls/.xlsx) contents
"""

import os
import re
import sys
from xlrd import open_workbook

# The plugin that loads the blob into the DB

def ProcessSheets(sheet):
    stripStupidVatSuffixes = re.compile(r'\.[0-9]*$')
    for rowIndex in xrange(0, sheet.nrows):
        sys.stdout.write(
            u";".join(
                unicode(sheet.cell(rowIndex, colIndex).value)
                for colIndex in xrange(0, sheet.ncols)))
        print


def main():
    if len(sys.argv) != 2:
        print "Usage:", os.path.basename(sys.argv[0]), " file.xls(x) ..."
        sys.exit(1)

    excelFiles = sys.argv[1:]
    for xls_filename in excelFiles:
        if not os.path.exists(xls_filename):
            print xls_filename, "not there! Aborting..."
            sys.exit(1)

    for xls_filename in excelFiles:
        try:
            book = open_workbook(xls_filename, on_demand=True)
            for name in book.sheet_names():
                sheet = book.sheet_by_name(name)
                ProcessSheets(sheet)
                book.unload_sheet(name)
        except Exception as e:
            print "Excel file failure: ", repr(e)
            sys.exit(1)


if __name__ == "__main__":
    main()
