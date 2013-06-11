#!/bin/bash
#
# If 'svn status' shows you lots of '?' but you checked
# them and know that they do not belong in the repos,
# then just run this, and all 'svn:ignore' of all
# folders will be updated to mark them as cruft.
#
# Note that you need to 'svn commit' after this.
#
propadd () {
  PROP=$1
  FILE=$2
  ADDVAL=$3
  OLDVAL=`svn propget $PROP $FILE`
  NEWVAL="$OLDVAL
$ADDVAL"
  echo svn propset $PROP \""$NEWVAL"\" $FILE
  svn propset $PROP "$NEWVAL" $FILE
}
svn status | grep '^?' | cut -c8- | while read file 
do 
	NFILE="`echo "$file" | sed 's,^.*/,,'`" 
	DIR="`echo "$file" | sed 's,/[^/]*$,,'`"
	if [ -z "$DIR" ] ; then DIR=. ; fi
	if [ "$DIR" == "$file" ] ; then DIR=. ; fi
	echo $NFILE
	echo $DIR
	propadd svn:ignore "$DIR" "$NFILE" 
done
