#!/usr/bin/env python2
'''
To be able to perform textual diff on two XML files,
I needed to sort their attributes and elements.
It was of no concern to XML parsers, but diff tools
(meld, vimdiff, etc) cared about it - a lot :-)

I am pretty sure this would be useful to many people.
Gotta write a blog post about it, someday...
'''

import re
import sys
import codecs
from xml.sax.handler import ContentHandler
import xml.sax


class Child:
    def __init__(self, name, attrs):
        self._name = name
        self._attrs = attrs
        self._children = []
        self._characters = ""


class InputFormatXMLHandler(ContentHandler):
    def __init__(self):
        ContentHandler.__init__(self)
        self._root = Child('root', {})
        self._parents = [self._root]
        self._ws = re.compile(r'^\s*$')

    def startElement(self, name, attrs):
        name = codecs.ascii_encode(name)[0]
        #parent = self._parents[-1]
        #print name, "under", parent._name
        #print attrs._attrs
        self._parents.append(Child(name, attrs))
        self._parents[-2]._children.append(self._parents[-1])

    def characters(self, content):
        if not re.match(self._ws, content):
            self._parents[-1]._characters += content

    def endElement(self, name):
        #print "/"+name
        self._parents.pop()


def Print(node, indent=""):
    s = indent + "<" + node._name
    if 0 != len(node._attrs):
        s += ' ' + " ".join(
            x+'="'+y+'"'
            for (x, y) in
            sorted(node._attrs.items(), key=lambda (x, y): x))
    s += ">"
    sys.stdout.write(s.encode("utf-8"))
    if node._characters != "":
        sys.stdout.write(node._characters.encode("utf-8"))
    if 0 != len(node._children):
        sys.stdout.write('\n')

    def elementSortKey(x):
        return x._name + "_".join(y+z for y, z in x._attrs.items())
    for c in sorted(node._children, key=elementSortKey):
        Print(c, indent + "   ")
    if 0 != len(node._children):
        sys.stdout.write(indent)
    sys.stdout.write("</" + node._name + ">\n")


def main():
    if len(sys.argv) != 2:
        sys.stderr.write("Missing or invalid path provided!\n")
        sys.exit(1)

    parser = xml.sax.make_parser()
    handler = InputFormatXMLHandler()
    parser.setContentHandler(handler)
    #parser.setFeature("http://xml.org/sax/features/validation", True)
    parser.parse(sys.argv[1])
    Print(handler._root)

if __name__ == "__main__":
    main()
