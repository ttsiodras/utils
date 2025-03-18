#!/bin/bash
# Convert a YAML file into a dot.notation output that you can grep on.
yq eval -o=json "$1" | jq -r 'paths(scalars) as $p | ($p | map(if type=="number" then "[" + (tostring) + "]" else . end) | join(".")) + " = " + (getpath($p) | tostring)'
