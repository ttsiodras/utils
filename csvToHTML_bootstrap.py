#!/usr/bin/env python3
import sys
import csv
from pathlib import Path
from textwrap import dedent


def main():
    filepaths, delimiter = get_cli_args()
    for f in filepaths:
        abspath = Path(f).resolve()
        htmlfilename = abspath.name.split(".")[0] + ".html"
        htmlfile = abspath.parent.joinpath(htmlfilename)
        # write the html file next to the csv with same name
        with open(htmlfile, "wt", encoding="utf-8") as f:
            print(f"Writing to {htmlfile.name}...")

            f.write(get_html_header())

            wroteHeader = False
            for row in get_csv_rows(abspath, delimiter):
                if not wroteHeader:
                    f.write('<thead><tr>')
                    for elem in row:
                        f.write(f"<td>{elem}</td>")
                    f.write("</tr></thead><tbody>")
                    wroteHeader = True
                    continue

                f.write("<tr>")
                for elem in row:
                    f.write(f"<td>{elem}</td>")
                f.write("</tr>")

            f.write("</tbody></table></div></body></html>")

            print(f"Completed writing to {htmlfile.name}")

    print("Done")


def get_csv_rows(csvpath, delimiter=","):
    with open(csvpath, "r", encoding="latin-1") as f:
        for row in csv.reader(f, delimiter=delimiter):
            yield row


def get_html_header():
    return dedent(
        f"""
        <html>
            <head>
                {get_bootstrap_cdn()}
            </head>
            <body>
                <div class="container">
                <table class="table table-striped">
        """
    )


def get_bootstrap_cdn():
    return dedent(
        """
        <link rel="stylesheet"
        href="https://stackpath.bootstrapcdn.com/bootstrap/4.3.1/css/bootstrap.min.css"
        integrity="sha384-ggOyR0iXCbMQv3Xipma34MD+dH/1fQ784/j6cY/iJTQUOhcWr7x9JvoRxT2MZw1T"
        crossorigin="anonymous">
        """
    )


def get_cli_args():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "csv_file_paths", nargs=argparse.REMAINDER, help="One or more csv file paths"
    )
    parser.add_argument("-d", "--delimiter", help="Specify CSV delimiter")
    args = parser.parse_args()
    filepaths = args.csv_file_paths
    delimiter = args.delimiter
    if not delimiter:
        delimiter = ","  # default
    return filepaths, delimiter


if __name__ == "__main__":
    main()
