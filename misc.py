'''
All the functions and classes that are commonly used from all my utilities.
'''
import re
import sys


def panic(msg):
    '''Print error message and abort'''
    if not msg.endswith('\n'):
        msg += "\n"
    if sys.stdout.isatty():
        sys.stderr.write("\n"+chr(27)+"[32m" + msg + chr(27) + "[0m\n")
    else:
        sys.stderr.write(msg)
    sys.exit(1)


class Matcher:
    '''Utility class for easy regexp work'''
    def __init__(self, pattern, flags=0):
        self._pattern = re.compile(pattern, flags)
        self._lastOne = None
        self._match = None
        self._search = None

    def match(self, line):
        '''match at start of line'''
        self._match = re.match(self._pattern, line)
        self._lastOne = 'Match'
        return self._match

    def search(self, line):
        '''match anywhere in the line'''
        self._search = re.search(self._pattern, line)
        self._lastOne = 'Search'
        return self._search

    def group(self, idx):
        '''return matched group'''
        if self._lastOne == 'Match':
            return self._match.group(idx)
        elif self._lastOne == 'Search':
            return self._search.group(idx)
        else:
            panic(
                "group() called with index %d before match/search!\n" % idx)

    def groups(self):
        '''return matched groups'''
        if self._lastOne == 'Match':
            return self._match.groups()
        elif self._lastOne == 'Search':
            return self._search.groups()
        else:
            panic("Matcher groups called with match/search!\n")
