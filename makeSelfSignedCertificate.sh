#!/bin/bash
if [ $# -ne 1 ] ; then
        echo Usage: $0 www.domain.com
        exit 1
fi
openssl genrsa -out $1.key 1024
echo
echo Here is a sample of the kind of input
echo that you need to input to the following questions...
echo
echo GR
echo Attiki
echo Athens
echo Semantix Information Technologies
echo Software Development
echo $1
echo ttsiodras@semantix.gr
echo
echo Here you GO...
echo
openssl req -new -key $1.key -out $1.csr
openssl x509 -req -days 9999 -in $1.csr -signkey $1.key -out $1.cert
chmod 400 $1.key
echo 
echo If you use apache, then...
echo you now copy $1.key to /etc/ssl/private
echo and $1.cert to /etc/ssl/certs
echo
echo If you use nginx, then...
echo you now copy $1.key to /etc/nginx/
echo and $1.cert to /etc/nginx/
echo and you write something like this in your sites-available/whatever
echo
echo "server {"
echo "  ssl_certificate $1.cert;"
echo "  ssl_certificate_key $1.key;"
echo "  listen 443 ssl;"
echo "}"
