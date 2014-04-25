#!/usr/bin/env python2
'''
This utility generates the password part of the /etc/kerio-kvc.conf file.
Example:

<config>
  <connections>
    <connection type="persistent">
      <server>vpn.neuropublic.com</server>
      <port>4090</port>
      <username>LOGIN_NAME</username>
      <password>XOR:OUTPUT_OF_THIS_UTILITY</password>
      <fingerprint>61:0B:2C:8A:DD:92:57:56:A8:06:62:FF:67:04:38:ED</fingerprint>
      <active>1</active>
    </connection>
  </connections>
</config>

'''

import sys

print "Password:",
password = raw_input()
for c in password:
    s = hex(85 ^ (ord(c)))
    sys.stdout.write(s[2:])
print
