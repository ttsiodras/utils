#!/bin/bash
# Show the color palette so you can choose a color in your .tmux.conf
for i in {0..255} ; do tput setaf $i ; echo -n "color$i  " ; tput sgr0 ; done
echo -e "\n\n========\n\nNow add a line like this one to your .tmux.conf:\n\tset -g status-bg color235"
