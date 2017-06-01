#!/bin/bash
#!/usr/bin/env vim
#! This is a bash script that executes itself as a vimscript to do its work
#! vim:ft=vim:ts=2:sts=2:sw=2

: if 0
  tmpfile=$(mktemp -t vimcat.XXXXXXXX)
  exec 9<>"$tmpfile"
  rm "$tmpfile"

  output="$(vim -e -X -R "$@" -c "source $0" -c "visual" -c "bufdo call AnsiHighlight()" -c qa 9>&1 &>/dev/null)"
  exec 9<&-
  echo "$output"
  exit
: endif

" AnsiHighlight:  Allows for marking up a file, using ANSI color escapes when
"                 the syntax changes colors, for easy, faithful reproduction.
" Author:         Matthew Wozniski (mjw@drexel.edu)
" Date:           Fri, 01 Aug 2008 05:22:55 -0400
" Version:        1.0 FIXME
" History:        FIXME see :help marklines-history
" License:        BSD. Completely open source, but I would like to be
"                 credited if you use some of this code elsewhere.

" Copyright (c) 2008, Matthew J. Wozniski                                {{{1
" All rights reserved.
" 
" Redistribution and use in source and binary forms, with or without
" modification, are permitted provided that the following conditions are met:
"     * Redistributions of source code must retain the above copyright
"       notice, this list of conditions and the following disclaimer.
"     * Redistributions in binary form must reproduce the above copyright
"       notice, this list of conditions and the following disclaimer in the
"       documentation and/or other materials provided with the distribution.
"     * The names of the contributors may not be used to endorse or promote
"       products derived from this software without specific prior written
"       permission.
" 
" THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDER ``AS IS'' AND ANY
" EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
" WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
" DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER BE LIABLE FOR ANY
" DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
" (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
" LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
" ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
" (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
" SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

" Turn off vi-compatible mode, unless it's already off                   {{{1
if &cp
  set nocp
endif

let s:type = 'cterm'
if &t_Co == 0
  let s:type = 'term'
endif

" Converts info for a highlight group to a string of ANSI color escapes  {{{1
function! s:GroupToAnsi(groupnum)
  if ! exists("s:ansicache")
    let s:ansicache = {}
  endif

  let groupnum = a:groupnum

  if groupnum == 0
    let groupnum = hlID('Normal')
  endif

  if has_key(s:ansicache, groupnum)
    return s:ansicache[groupnum]
  endif

  let fg = synIDattr(groupnum, 'fg', s:type)
  let bg = synIDattr(groupnum, 'bg', s:type)
  let rv = synIDattr(groupnum, 'reverse', s:type)
  let bd = synIDattr(groupnum, 'bold', s:type)

  " FIXME other attributes?

  if rv == "" || rv == -1
    let rv = 0
  endif

  if bd == "" || bd == -1
    let bd = 0
  endif

  if rv
    let temp = bg
    let bg = fg
    let fg = temp
  endif

  if fg >= 8 && fg < 16
    let fg -= 8
    let bd = 1
  endif

  if fg == "" || fg == -1
    unlet fg
  endif

  if !exists('fg') && !groupnum == hlID('Normal')
    let fg = synIDattr(hlID('Normal'), 'fg', s:type)
    if fg == "" || fg == -1
      unlet fg
    endif
  endif

  if bg == "" || bg == -1
    unlet bg
  endif

  if !exists('bg') && !groupnum == hlID('Normal')
    let bg = synIDattr(hlID('Normal'), 'bg', s:type)
    if bg == "" || bg == -1
      unlet bg
    endif
  endif

  "let retv = "\<Esc>[22;24;25;27;28;49" " I added 49 to reset default background
  let retv = "\<Esc>[0" " Why didn't the script use this all along? Doesn't it work everywhere?

  if bd
    let retv .= ";1"
  endif

  if exists('fg') && fg < 8
    let retv .= ";3" . fg
  elseif exists('fg')
    let retv .= ";38;5;" . fg " 38;5 is for 256-color xterm
  endif

  if exists('bg') && bg < 8
    let retv .= ";4" . bg
  elseif exists('bg')
    let retv .= ";48;5;" . bg " 48;5 is for 256-color xterm
  endif

  let retv .= "m"

  let s:ansicache[groupnum] = retv

  return retv
endfunction

function! AnsiHighlight()
  let retv = []

  for lnum in range(1, line('$'))
    let last = hlID('Normal')
    let output = s:GroupToAnsi(last) . "\<Esc>[K" " Clear to right

    " Hopefully fix highlighting sync issues
    exe "norm! " . lnum . "G$"

    let line = getline(lnum)

    for cnum in range(1, col('.'))
      if synIDtrans(synID(lnum, cnum, 1)) != last
        let last = synIDtrans(synID(lnum, cnum, 1))
        let output .= s:GroupToAnsi(last)
      endif

      let output .= matchstr(line, '\%(\zs.\)\{'.cnum.'}')
      "let line = substitute(line, '.', '', '')
      "let line = matchstr(line, '^\@<!.*')
    endfor

    let retv += [output]
  endfor

  " Reset the colors to default after displaying the file
  let retv[-1] .= "\<Esc>[0m"

  "return writefile(retv, '/proc/self/fd/9')
  return writefile(retv, '/dev/fd/9')
endfunction