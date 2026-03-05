#!/bin/bash
tmux -L corundum new-session -d
cd ~/dotfiles/tmux-resurrect/scripts/ || exit 1
ln -sf ~/.tmux/resurrect/"$1".txt ~/.tmux/resurrect/last
tmux -L corundum run-shell "~/dotfiles/tmux-resurrect/scripts/restore.sh"
tmux -L corundum attach
