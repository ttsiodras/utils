#!/bin/bash
# Auto-preview files as you move along
fzf +s --preview 'bat --style numbers,changes --color=always {} | head -500'
